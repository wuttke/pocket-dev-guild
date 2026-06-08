# Pocket Dev Guild

A small FastAPI service for managing git worktrees and running a coding
agent CLI (`auggie` by default) inside them. Output streams live to the
browser via Server-Sent Events; conversation context is preserved
across turns by resuming the agent's own session.

> **API reference**: the running server publishes a typed OpenAPI 3
> document. Browse it at <http://localhost:8000/api/docs> (Swagger) or
> <http://localhost:8000/api/redoc>. The committed `openapi.json` is the
> same document for offline tooling. All API endpoints are available under
> the `/api` prefix, while the frontend is served from `/`.

## Quickstart

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

cp config.example.yaml config.yaml
$EDITOR config.yaml          # set mongodb_url etc.

.venv/bin/uvicorn main:app --reload
```

Then open <http://localhost:8000/> for the minimal built-in UI.

Override the config path with `POCKET_DEV_GUILD_CONFIG=/path/to.yaml`.

## Configuration (`config.yaml`)

```yaml
# Which agent to invoke and how it takes its prompt. Defaults shown.
agent_binary: auggie
agent_prompt_param: --print

# Optional. Without this, jobs, conversations, and repositories live
# in memory and are lost on restart.
mongodb_url: mongodb://localhost:27017/pocket_dev_guild
```

## Concepts

### Repos, worktrees, and the path layout

A **repo** is a registry entry pointing at an existing git clone on
disk. Repositories are stored in the database (when MongoDB is configured)
or in-memory (for development without MongoDB). You can:
- Register existing repositories via `POST /repos`
- Clone new repositories via `POST /repos/clone`

**Worktrees** are created next to the repo using a fixed convention so
they're easy to find and to clean up:

```
{repo_parent}/{repo_name}-worktrees/{worktree_name}
```

Worktree names and repo ids must match `^[A-Za-z0-9_-]+$`. Branch names
follow `kind/slug[/slug...]` where the first segment is letters only
(`feature/foo`, `Hotfix/v2.5.x`). These rules rule out path traversal
and shell metacharacters in arguments that flow into `git` calls.

### Jobs

A **job** is one invocation of the agent CLI: a subprocess that runs
inside a worktree, gets a prompt, and streams stdout/stderr lines as
they arrive. Each job has a lifecycle:

```
queued ──► running ──► finished      (exit 0)
                  ╲──► failed        (non-zero exit or spawn error)
                  ╲──► cancelled     (DELETE /api/jobs/{id})
```

Cancellation sends `SIGTERM` to the subprocess, waits 5 s, then
escalates to `SIGKILL`. Jobs that have not spawned yet flip status
directly. Either way the terminal state is `cancelled` with
`finished_at` stamped — distinct from `failed` so the UI can render
user-initiated stops differently from crashes.

Jobs are **only** created through conversations (see below). There is
no public endpoint that creates a free-standing job.

### Conversations and session resume

A **conversation** is an ordered list of jobs that share an agent
session. The first turn discovers the agent's session id from the
`Request ID` line that `auggie` prints to stdout; subsequent turns
pass `--resume <session_id>` to the same binary, so the agent
remembers earlier context without the service having to replay any
history.

Conversations carry a `busy` flag for the duration of each turn so the
router can reject parallel turns with `409 Conflict`. A `summary`
field is filled by a cheap follow-up `--print` call after each
successful turn, used by the UI to render conversation list rows.

Conversations can be `archived` (soft-delete): they vanish from the
default listing and reject new turns, but the rows stay so existing
`Job.conversation_id` references still resolve.

### SSE: how live updates work

Two endpoints stream Server-Sent Events:

- `GET /api/jobs/{id}/events` — `log` events (stdout/stderr lines), then
  one final `status` event when the job reaches a terminal state.
- `GET /api/conversations/{id}/events` — state changes on the conversation
  itself (new turn started, summary updated, archived).

The push side is a `NotificationHub`: an in-memory map of
`asyncio.Condition` objects keyed by job/conversation id. When the
store persists a new log line or status change it calls
`hub.notify(key)`, which wakes the SSE generator. No polling loop.

This makes the hub strictly per-process state: if you run more than
one server instance behind a load balancer, SSE clients only see
updates from the instance that owns the live subprocess. See
`MULTIPLE_INSTANCES.md` for the planned multi-node strategy.

### Persistence: in-memory vs. MongoDB

`JobStore` and `ConversationStore` are pluggable. Without
`mongodb_url` in config they're plain dicts in memory — fine for
local development, lost on restart. Set `mongodb_url` and the same
APIs are served by `MongoJobStore` and `ConversationStore(backend=
MongoBackend(...))` against the configured database.

On startup with Mongo enabled, the lifespan hook runs `fail_orphans`:
any job left `running` by a previous process is flipped to `failed`,
because its subprocess died with that process. (This is single-node
behaviour — the hook is gated for the multi-instance future.)

### Referential integrity

`DELETE /api/repos/{id}/worktrees/{name}` refuses to remove a worktree
while it has unarchived conversations or active (queued/running) jobs.
It returns `409 Conflict` with a structured body so the UI can prompt
the user to archive conversations or cancel jobs first:

```json
{
  "reason": "worktree-busy",
  "worktree": "feature-a",
  "conversations": 2,
  "active_jobs": 1,
  "hint": "Archive conversations and cancel running jobs first."
}
```

## Interesting flows

### Starting a conversation and its first turn

```
POST /api/conversations            { repo_id, worktree, title? }
  └─► ConversationStore.create → ConversationInfo (busy=false, turns=[])

POST /api/conversations/{id}/turns { prompt }
  ├─► mark conversation busy
  ├─► JobStore.create (status=queued, conversation_id=…)
  ├─► schedule run_conversation_turn as asyncio.Task
  └─► return JobCreated (job_id, location: /api/jobs/{id}/events)

  ── background ──
  runner.run(job_id, cwd, prompt)
    ├─► spawn `auggie --print "<prompt>"` in worktree cwd
    ├─► stream lines → JobStore.append_log → hub.notify(job_id)
    ├─► capture Request ID from stdout
    └─► on exit: store.set_status(finished|failed) → hub.notify(job_id)

  runner.discover_session(request_id) → session_id
  conversations.patch(id, session_id=…)
  runner.summarize(cwd, session_id) → summary
  conversations.patch(id, summary=…); mark busy=false
```

The client meanwhile holds an `EventSource` open on
`/jobs/{id}/events`, sees the log lines as they're appended, and gets
one terminal `status` event when the runner exits.

### Resuming on the second turn

`POST /api/conversations/{id}/turns` looks up the stored `session_id` and
passes it to `runner.run(..., session_id=…)`, which appends
`--resume <id>` to the `auggie` invocation. No state on the
service side needs to be re-sent; the agent reloads its own session.

### Cancelling a running job

```
DELETE /api/jobs/{id}
  ├─► 404 if unknown
  ├─► 409 if already finished/failed/cancelled
  └─► runner.cancel(id):
        ├─► record cancellation flag
        ├─► if subprocess registered: SIGTERM, wait ≤ 5s, else SIGKILL
        └─► return True/False (was it signalled?)
      if not signalled (queued): store.set_status("cancelled")
      else: runner's run-loop flips status when subprocess exits
```

The SSE stream on `/jobs/{id}/events` emits a final `status` event
with `status: "cancelled"` and closes.

## Architecture

```
pocket_dev_guild/
├── app.py                      # create_app() factory; DI via app.state
├── config.py                   # Settings + RepoRegistry (reads config.yaml)
├── schemas.py                  # Pydantic models → typed OpenAPI
├── deps.py                     # FastAPI dependency providers
├── routers/
│   ├── repos.py
│   ├── worktrees.py            # incl. 409 referential-integrity guard
│   ├── jobs.py                 # SSE log stream + cancellation
│   ├── conversations.py        # SSE state stream, turn dispatch
│   └── _pagination.py          # shared list/sort/limit parsing
└── services/
    ├── git_service.py          # async `git worktree` wrapper
    ├── notification_hub.py     # asyncio.Condition pub/sub for SSE
    ├── job_store.py            # in-memory job store
    ├── mongo_job_store.py      # Mongo-backed job store
    ├── repo_store.py           # repository registry, in-memory or Mongo
    ├── conversation_store.py   # conversations over a StorageBackend
    ├── storage_backend.py      # InMemoryBackend / MongoBackend
    ├── augment_runner.py       # Protocol + SubprocessAugmentRunner
    └── conversation_orchestrator.py  # one turn end-to-end
```

Key design choices:

- **Async everywhere.** `git` and the agent run via
  `asyncio.create_subprocess_exec`; the event loop never blocks.
- **Push-based SSE via `NotificationHub`.** A shared hub fans out
  notifications for both job and conversation streams. No polling.
- **Protocol-based runner.** `AugmentRunner` is a Protocol so tests
  inject `FakeRunner` and exercise routes + SSE without spawning real
  subprocesses.
- **Dependency injection through `app.state`.** Stores, runner and
  registry are attached at app-build time; every router resolves them
  through `Depends` providers in `deps.py` so tests can swap any of
  them per fixture.

## Tests

```bash
.venv/bin/pytest
```

The suite uses FastAPI's `TestClient`, a `FakeGit` that records calls
in memory, and a `FakeRunner` that replays a scripted sequence of log
lines into the real `JobStore` — exercising SSE end-to-end without
spawning any real subprocesses. The Mongo backends have their own
integration tests that run against a local MongoDB if reachable.

## Roadmap

See `TODO.md` for the prioritised list. The headline open items are
**auth** (currently anyone who can reach `/jobs` runs the agent),
**multi-agent support** (the runner is hard-wired to `augment`), and
the **frontend rewrite** to a real Vite/React/Shadcn app.
