# Pocket Dev Guild

A small FastAPI web app that lists git repositories from a config file,
manages their worktrees, and runs the `augment` CLI inside a chosen
worktree — streaming its output live to the browser via Server-Sent
Events.

## Quickstart

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# point config.yaml at your real repos
cp config.example.yaml config.yaml
$EDITOR config.yaml

.venv/bin/uvicorn main:app --reload
```

Open <http://localhost:8000/> for the minimal UI, or
<http://localhost:8000/docs> for Swagger / <http://localhost:8000/redoc>
for ReDoc.

The config path can be overridden via the `POCKET_DEV_GUILD_CONFIG`
environment variable.

## API

| Method | Path                                 | Purpose                       |
| ------ | ------------------------------------ | ----------------------------- |
| GET    | `/repos`                             | List configured repositories  |
| GET    | `/repos/{repo_id}/worktrees`         | List git worktrees            |
| POST   | `/repos/{repo_id}/worktrees`         | Add a worktree                |
| DELETE | `/repos/{repo_id}/worktrees/{name}`  | Remove a worktree             |
| POST   | `/jobs`                              | Start an augment run          |
| GET    | `/jobs/{job_id}`                     | Job metadata                  |
| GET    | `/jobs/{job_id}/log`                 | Full log snapshot             |
| GET    | `/jobs/{job_id}/events`              | SSE stream of logs + status   |

Worktrees are created next to the repo:
`{repo_parent}/{repo_name}-worktrees/{worktree_name}`.

## Architecture

```
pocket_dev_guild/
├── app.py                  # create_app() factory, DI via app.state
├── config.py               # Settings + RepoRegistry (reads config.yaml)
├── schemas.py              # All Pydantic models → typed OpenAPI
├── deps.py                 # FastAPI dependency providers
├── services/
│   ├── git_service.py      # async git worktree wrapper
│   ├── job_store.py        # in-memory store with asyncio.Condition push
│   └── augment_runner.py   # Protocol + subprocess implementation
└── routers/
    ├── repos.py
    ├── worktrees.py
    └── jobs.py             # incl. SSE endpoint
```

Key design choices:

- **Async everywhere.** Both `git worktree` and the `augment` subprocess
  run via `asyncio.create_subprocess_exec`, so the event loop never
  blocks on I/O.
- **Push-based SSE.** The job store wakes up the SSE generator with an
  `asyncio.Condition` whenever a new log line arrives or the job
  finishes — no polling loop.
- **Dependency injection.** Routes resolve `RepoRegistry`, `GitService`,
  `JobStore` and the `AugmentRunner` from `app.state`, which makes them
  trivially replaceable in tests.

## Tests

```bash
.venv/bin/pytest
```

The test suite uses FastAPI's `TestClient`, a `FakeGit` that records
calls in memory, and a `FakeRunner` that replays a scripted sequence of
log lines into the real `JobStore` — exercising the SSE endpoint end to
end without spawning any real subprocesses.
