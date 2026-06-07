# TODO

## Auth

Anyone who can reach `/jobs` can execute the `augment` CLI inside any
configured repo. Acceptable while bound to `127.0.0.1`, not acceptable
once exposed.

- [ ] Decide auth model: single shared token (header / query) vs. real
      user accounts vs. reverse-proxy auth (oauth2-proxy, Tailscale,
      Cloudflare Access).
- [ ] Add an `Authentication` dependency that all routers depend on,
      configurable via `Settings` (so tests can disable it).
- [ ] Per-repo ACLs? (e.g. `repos[*].allowed_users`)
- [ ] CSRF for state-changing endpoints once cookies are in play.

## `GET /agents`

Right now the runner is hard-coded to invoke `augment`. We want to
support multiple CLI agents (augment, claude, codex, custom scripts)
and let the UI pick one per job.

- [ ] Introduce an `Agent` model: `{id, name, command, args_template,
      env}` — loaded from `config.yaml` next to `repos`.
- [ ] `GET /agents` returns the configured list (typed schema).
- [ ] `POST /jobs` accepts an `agent_id`; default stays `augment` for
      backwards compatibility.
- [ ] `AugmentRunner` becomes a generic `AgentRunner` that resolves the
      agent by id and renders the prompt into the args template.
- [ ] Tests: fake agents covering happy path + unknown-agent-id 404.

## Job persistence

In-memory `JobStore` — restart drops every job, log, and status. Fine
for dev, painful otherwise.

- [ ] Pick a backend (SQLite via `aiosqlite` is the smallest step;
      Postgres if we ever go multi-instance).
- [ ] Schema: `jobs(id, repo_id, worktree, agent_id, prompt, status,
      created_at, finished_at, exit_code)` + `job_log(job_id, seq,
      stream, line, ts)`.
- [x] Expose `created_at` / `finished_at` (UTC, ISO-8601) on `JobInfo`
      and in the SSE `status` event, so the UI can show
      "running for 4m12s" / "finished 2025-06-07 14:03". (already wired
      through the in-memory store; the DB layer just needs to persist
      the same values.)
- [ ] Keep the `asyncio.Condition` push semantics on top of the DB —
      writes notify in-process subscribers, SSE generator reads new
      rows by `seq > last_seq`.
- [ ] Migration story: Alembic, or a single `schema.sql` applied on
      startup.
- [ ] Retention / pruning (cap log lines per job, delete jobs older
      than N days).
- [ ] `GET /jobs` listing endpoint with pagination + status filter.

## Frontend

`static/index.html` is a 125-line crutch. Good enough to prove the
backend works, not good enough to live with.

- [ ] Decide stack: keep vanilla + a tiny component lib, or commit to
      Vite + React/Svelte.
- [ ] Repo / worktree browser with create + delete (currently a single
      select).
- [ ] Job list view (uses the future `GET /jobs`) with live status
      column.
- [ ] Job detail page: streaming log via SSE, kill button (once the
      cancel endpoint exists), exit code + duration.
- [ ] Agent picker once `GET /agents` lands.
- [ ] Generate a typed client from `/openapi.json` (e.g. `openapi-ts`)
      so the frontend doesn't hand-roll request shapes.

### Pretty log rendering (ANSI handling)

Agent CLIs like `auggie` emit ANSI escape sequences (e.g. `ESC[90m` for
gray, `ESC[0m` reset, `ESC[2K` clear line, `ESC[?25l/h` cursor on/off)
even when stdout is a pipe. The browser shows the raw `␛[…m` bytes in
the `<pre>` log instead of formatting.

Three options, in order of effort:

- [ ] **Disable colors at the source** (simplest, no UI work): pass
      `NO_COLOR=1` and `TERM=dumb` in the subprocess env from
      `SubprocessAugmentRunner`. De-facto standard, respected by most
      modern CLIs. Trade-off: no color information at all.
- [ ] **Strip on the server**: drop ANSI sequences in
      `SubprocessAugmentRunner._pump` with a regex like
      `re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line)` before storing the
      `LogLine`. Same visual result as option 1, but keeps colored
      output available for terminal users running the CLI directly.
- [ ] **Render in the browser**: convert ANSI to `<span style="…">`
      client-side (e.g. [`ansi_up`](https://github.com/drudru/ansi_up),
      ~3 kB). Output matches what the user sees in their terminal —
      colors, bold, dimmed text. Needs a small DOM change in
      `static/index.html` (insert HTML instead of appending text) and
      careful escaping of the non-ANSI parts.

Recommendation when the frontend gets rewritten: option 3 alongside the
agent picker, so log readability scales with the multi-agent story.


## Conversations (multi-turn jobs)

Today each `POST /jobs` is independent — every turn pays full agent
startup cost, has no shared context, and the UI can't tell that two
jobs in the same worktree belong together. We want **Conversations**:
named, ordered sequences of jobs that share agent state across turns.

### Findings that shape the design

- `auggie --print` writes session history to `~/.augment/sessions/`
  (per workspace root) even in one-shot mode. Confirmed via
  `auggie session list --all --json`.
- `auggie --print --resume <sessionId>` **works** and **survives the
  workspace being deleted** — resumed sessions answer from history
  even when the original worktree is gone. Verified end-to-end.
- `auggie session list --all --json` gives us `{sessionId, created,
  modified, exchangeCount, workspaceRoot, firstUserMessage,
  lastUserMessage, requestIds[]}` — enough metadata to rebuild a
  conversation index on demand.
- Cheap summary turns are possible: `auggie --print --ask
  --mcp-config <empty.json> --dont-save-session` runs in ~10 s with no
  MCP boot and produces a clean answer from session history alone.

### V1 model — "worktree-as-stage, session-as-thread"

- A `Conversation` is `{id, repo_id, worktree, agent_id, title,
  session_id, summary, created_at, updated_at}`. `session_id` is the
  agent-native id (auggie session UUID); when the conversation moves
  to another agent, we start a fresh `session_id` and keep history in
  our own log.
- Each `Job` gains optional `conversation_id`. The runner passes
  `--resume <session_id>` (or the equivalent for other agents) when
  `conversation_id` is set and the conversation already has a
  `session_id`. The first job in a conversation creates the session;
  later turns resume it.
- The worktree is the **stage** (filesystem state for that turn). The
  session is the **thread** (agent-side memory). They can outlive each
  other: deleting a worktree doesn't kill the conversation, ending a
  conversation doesn't touch the worktree.

### REST surface

- `POST /conversations` — `{repo_id, worktree, agent_id, title?}` →
  returns a `Conversation` with empty `session_id`.
- `GET /conversations` — list with pagination + `repo_id` filter.
- `GET /conversations/{id}` — metadata + turn list (job ids + status +
  timestamps + truncated prompt).
- `POST /conversations/{id}/turns` — `{prompt}` → creates a `Job`
  bound to the conversation, returns `{job_id}`. SSE stays on
  `/jobs/{job_id}/events`.
- `POST /conversations/{id}/summary` — runs the cheap summary agent
  (empty MCP, `--ask`, `--dont-save-session`) over the current
  `session_id`, stores the result in `Conversation.summary`. Returns
  the new summary. UI can call this after every turn or on demand.
- `DELETE /conversations/{id}` — drops our row; optionally also calls
  `auggie session delete <session_id>` to clean up agent-side state
  (configurable, default keep).

### Frontend hooks (later, with the rewrite)

- Conversation sidebar grouped by repo → worktree, newest first,
  showing title (or first prompt) + last-update relative time.
- Selecting a conversation shows the turn list with per-job duration
  and the latest summary at the top — so the user sees "what this
  thread is about" without scrolling through logs.
- "Continue" button = `POST /conversations/{id}/turns` with the
  current prompt textarea content. "Summarize" button = manual
  trigger of the summary endpoint.

### Cross-cutting

- Conversation rows belong in the same DB as jobs (see persistence
  section); in-memory `ConversationStore` is fine for the first pass
  to keep the diff small.
- Multi-agent in one conversation is **out of scope for V1** — auggie
  sessions are auggie-only and `claude` / `codex` will have their own
  resume models. We can revisit once a second agent is wired in.
- Branching ("fork conversation at turn N") is **out of scope for
  V1** — would need worktree snapshots and a separate session id per
  branch.
- Parallel turns in the same conversation are **forbidden** for V1
  (single in-flight job per conversation). Enforce in the POST
  handler; surface as 409.

### Decisions

- **One agent per conversation** — locked at creation
  (`POST /conversations` requires `agent_id`). No agent switching
  mid-thread; if the user wants a different agent, that's a new
  conversation.
- **Auto-summary after every terminal turn** — once the main job
  reaches status `finished`, the server kicks off a summary turn
  asynchronously and updates `Conversation.summary` when it returns.
  The UI subscribes to a `summary` SSE event (or polls) to refresh.
  No explicit "summarize" button needed for V1.
- **Summary runs in the same session** — same `agent_id`, resume the
  same `session_id`, but with `--dont-save-session` so the summary
  exchange doesn't pollute the agent-side chat history. No separate
  `auggie-summary` profile needed.
- **Summary output channel** — call
  `auggie --print --resume <session_id> --dont-save-session
  --mcp-config <empty.json> --output-format json -i "<summary prompt>"`.
  Parse the single JSON line, take `.result` (assistant message),
  check `.is_error`. No SSE — store the text and notify subscribers.
- **Worktree deletion is ignored for V1** — sessions survive deleted
  worktrees (verified). If the user runs a new turn in a conversation
  whose worktree is gone, the runner returns a 4xx with a clear
  message. No `worktree_missing` flag, no UI gating.
- **Session-id discovery via JSON output** — auggie's
  `--output-format json` emits `session_id` and `request_id` directly
  in the result line, so the runner just reads them. This replaces
  the earlier idea of scanning `~/.augment/sessions/*.json` for the
  matching `chatHistory[].exchange.request_id` (still a valid
  fallback, but not needed when JSON output is available).
  - **Main turn**: text mode is preferred for live SSE streaming.
    After the job ends, the runner captures the trailing
    `Request ID: <uuid>` line from stdout and — only on the **first**
    turn of a conversation — calls `auggie session list --all --json`
    to find the session whose `requestIds[]` contains it. From turn 2
    onwards, `session_id` is already known and is passed via
    `--resume`.
  - **Summary turn**: always `--output-format json`; read
    `session_id` directly (sanity check it matches the conversation's
    stored id).

### Implementation order

1. `ConversationStore` (in-memory, mirrors `JobStore`) +
   `POST /conversations`, `GET /conversations`, `GET /conversations/{id}`.
2. Extend `JobCreate` with optional `conversation_id`; runner pulls
   `agent_id`, `worktree`, and existing `session_id` from the
   conversation when set, and rejects mismatches.
3. Runner captures `Request ID:` from stdout; on first turn of a
   conversation, look up `session_id` via
   `auggie session list --all --json` and patch it back onto the
   conversation.
4. From turn 2 onwards, prefix args with `--resume <session_id>`.
5. After every `finished` job that belongs to a conversation,
   schedule a background coroutine that runs the JSON-mode summary
   and updates `Conversation.summary` + emits a `summary` event.
6. Frontend: minimal "Conversations" sidebar (list + select + new
   turn) — full UI work tracked in the Frontend section.
