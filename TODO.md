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
