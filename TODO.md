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
