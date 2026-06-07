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
and let the UI pick one per conversation.

Jobs are always created through conversations (`POST /conversations`
then `POST /conversations/{id}/turns`), so the agent is selected once
at conversation creation and inherited by every turn of that
conversation. `ConversationCreate`/`ConversationInfo` already carry an
optional `agent_id` field — wiring it through to the runner is the
remaining work.

- [ ] Introduce an `Agent` model: `{id, name, command, args_template,
      env, supports_resume}` — loaded from `config.yaml` next to
      `repos`.
- [ ] `GET /agents` returns the configured list (typed schema).
- [ ] `POST /conversations` validates `agent_id` against the configured
      agents (404 on unknown id); default stays `augment` for backwards
      compatibility when omitted.
- [ ] `run_conversation_turn` reads `conversation.agent_id` and passes
      it to the runner; `AugmentRunner` becomes a generic `AgentRunner`
      that resolves the agent and renders the prompt into the args
      template.
- [ ] Per-agent session discovery: only `augment` writes to
      `~/.augment/sessions/`; other agents need their own discovery
      hook (or skip resume entirely if `supports_resume=false`).
- [ ] `GET /conversations` / `GET /jobs` expose the resolved `agent_id`
      so the UI can render the agent badge per conversation/job.
- [ ] Tests: fake agents covering happy path, unknown-agent-id 404 on
      conversation create, and conversation turns picking up the
      agent_id from the parent conversation.

## Persistence

✅ **MongoDB backend implemented** for jobs and conversations.
- [x] MongoDB integration with `motor` (async driver)
- [x] Job and conversation persistence
- [x] Configurable via `mongodb_url` in `config.yaml`
- [x] Timestamps (`created_at`, `finished_at`, `updated_at`)
- [ ] Retention / pruning (cap log lines per job, delete old jobs/conversations)

## Jobs API

✅ **Core endpoints implemented**.
- [x] `GET /jobs` listing endpoint with pagination
  - Query params: `limit`, `offset`, `repo_id`, `worktree`, `status`, `conversation_id`, `sort`
  - Response: `{items: [...], total, limit, offset}`
- [x] `DELETE /jobs/{job_id}` to cancel running/queued jobs (SIGTERM
      with SIGKILL fallback; terminal status `cancelled`)

## Frontend Rewrite

See **FRONTEND.md** for complete frontend developer guide.

**Stack**: Vite + React + TypeScript + TanStack Query + Tailwind + Shadcn/ui

✅ **Current vanilla HTML (`static/index.html`)**:
- [x] Repo / worktree browser with create + **delete**
- [x] Conversation support (create, list, send turns, SSE updates)
- [x] Real-time log streaming via SSE
- [x] Support for creating new or checking out existing branches

**Needed for production**:
- [ ] Mobile-first responsive UI (bottom nav on mobile, sidebar on desktop)
- [ ] **Worktree delete UI** (swipe-to-delete on mobile, delete button on desktop)
- [ ] Job list view UI (backend `GET /jobs` is in place)
- [ ] Paginated conversation list UI (backend pagination is in place)
- [ ] Virtual scrolling for long logs
- [ ] ANSI escape sequence rendering (use `ansi-to-react`)
- [ ] Keyboard shortcuts
- [ ] Dark mode
- [ ] PWA features (manifest, service worker, offline support)
