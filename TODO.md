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

## Multi-Agent Support

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

## Job & Conversation Persistence (MongoDB)

✅ **Status**: MongoDB backend implemented for both jobs and conversations.
- [x] MongoDB integration with `motor` (async driver)
- [x] Conversation persistence with MongoDB backend
- [x] `created_at` / `finished_at` timestamps on `JobInfo`
- [x] Configurable via `mongodb_url` in `config.yaml`
- [ ] Migration to MongoDB-only (remove in-memory fallback)
- [ ] Schema indexes for performance
- [ ] Retention / pruning (cap log lines per job, delete old jobs)

## Jobs API

- [ ] `GET /jobs` listing endpoint with pagination
  - Query params: `limit`, `offset`, `repo_id`, `status`, `conversation_id`, `sort`
  - Response: `{jobs: [...], total, limit, offset}`
- [ ] `DELETE /jobs/{job_id}` to cancel/kill running jobs
- [ ] Job log truncation (cap at N lines, stream remaining)

## Conversations API

✅ **Status**: Core conversation endpoints implemented.
- [x] `POST /conversations` — create conversation
- [x] `GET /conversations` — list conversations (with `repo_id` filter)
- [x] `GET /conversations/{id}` — get conversation details
- [x] `POST /conversations/{id}/turns` — add turn to conversation
- [x] `GET /conversations/{id}/events` — SSE stream of conversation state
- [ ] `DELETE /conversations/{id}` — archive/delete conversation
- [ ] Add `archived` field to `ConversationInfo`
- [ ] Pagination support for `GET /conversations`
  - Query params: `limit`, `offset`, `status`, `worktree`, `updated_since`, `sort`
- [ ] More filters: `status`, `worktree`, `updated_since`

## Frontend Rewrite

See **FRONTEND.md** for complete frontend developer guide.

**Stack**: Vite + React + TypeScript + TanStack Query + Tailwind + Shadcn/ui

✅ **Current vanilla HTML (`static/index.html`)**:
- [x] Repo / worktree browser with create + **delete**
- [x] Conversation support (create, list, send turns, SSE updates)
- [x] One-shot job mode
- [x] Real-time log streaming via SSE
- [x] Support for creating new or checking out existing branches

**Needed for production**:
- [ ] Mobile-first responsive UI (bottom nav on mobile, sidebar on desktop)
- [ ] Job list view (requires `GET /jobs`)
- [ ] Paginated conversation list
- [ ] Virtual scrolling for long logs
- [ ] ANSI escape sequence rendering (use `ansi-to-react`)
- [ ] Keyboard shortcuts
- [ ] Dark mode
- [ ] PWA features (manifest, service worker, offline support)


## Additional Backend TODOs

### Performance & Monitoring
- [ ] Add request logging middleware
- [ ] Implement health check endpoint (`GET /health`)
- [ ] Add metrics collection (Prometheus, StatsD)
- [ ] Log rotation for job logs
- [ ] Connection pooling for MongoDB

### Error Handling
- [ ] Custom exception handlers for common errors
- [ ] Structured error responses with error codes
- [ ] Better validation error messages

### Configuration
- [ ] Environment variable support for all config options
- [ ] Config hot-reload without restart
- [ ] Validate config schema on startup

### Git Operations
- [ ] Add `git fetch` before creating worktrees
- [ ] Support for remote branches (not just `origin`)
- [ ] Worktree prune on startup (remove stale entries)
- [ ] Better error messages for git failures

### Job Cancellation
- [ ] `DELETE /jobs/{job_id}` to kill running jobs
- [ ] Send SIGTERM to subprocess, SIGKILL after timeout
- [ ] Update job status to `cancelled`
- [ ] SSE event for cancellation

### Rate Limiting
- [ ] Per-IP rate limiting for job creation
- [ ] Per-repo rate limiting
- [ ] Configurable limits in `config.yaml`
