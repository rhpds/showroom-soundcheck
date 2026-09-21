# AGENTS.md

Agent-facing conventions and gotchas for Showroom Soundcheck. For the full architecture diagram, tech stack versions, environment variables, and user-facing docs, see [README.md](README.md). For specialized one-off review/test/audit tasks, see [.cursor/prompts/](.cursor/prompts/) — those prompts assume you've read this file.

## Overview

Soundcheck is a session-based health check tool for showroom lab environments: it resolves Babylon GUIDs/workshops/resource pools to showroom URLs and runs async health checks with live-streamed results. Backend: FastAPI + SQLModel + SAQ (async task queue) + Redis + PostgreSQL. Frontend: SvelteKit 2 + Svelte 5 runes + PatternFly v6.

## Project structure

- `backend/soundcheck/routes/` — thin FastAPI route handlers; delegate logic to `services/`.
- `backend/soundcheck/services/` — business logic (health checks, Babylon/K8s resolution, session/group orchestration, workshop dashboard data).
- `backend/soundcheck/tasks/` — SAQ background jobs (`orchestration.py` coordinators, `checks.py` leaf tasks, `events.py` Pub/Sub helpers).
- `backend/soundcheck/{models,schemas,schemas_workshops}.py` — SQLModel tables and Pydantic request/response schemas.
- `backend/soundcheck/config.py` — the *only* place env vars are read (see Conventions below).
- `frontend/src/routes/` — SvelteKit file-based pages (sessions, groups, workshops, deep-link `check`).
- `frontend/src/lib/components/` — shared Svelte components; `lib/api.ts` is the typed REST client; `lib/checkStatuses.svelte.ts` is a runes-based shared state module (not a plain utility file).

Full, current file trees live in README.md's Architecture section — don't duplicate them here; update README instead if the tree changes.

## Commands

```bash
podman compose up -d          # or: docker compose up -d — full local stack
make lint / make format / make check     # ruff + eslint + svelte-check
cd backend && python -m pytest           # backend tests
cd frontend && npm run check             # svelte-check + type check
```

## Architectural rules agents must not violate

- **SAQ two-queue design**: `orchestration` queue holds lightweight coordinators that fan out fire-and-forget jobs and return immediately; `checks` queue holds leaf tasks (`check_target`) with no children. Never enqueue a job back onto the same queue it's running on — that risks deadlock. The last sibling leaf task to finish calls `_try_finalize_session()` (last-writer-finalizes); `sweep_stale_sessions` (cron, every 5 min) is the safety net for lost/crashed jobs.
- **Streaming-first, no polling**: the flow is REST POST enqueues a job → SAQ worker → Redis Pub/Sub → SSE endpoint → browser `EventSource`. Never add `setInterval`/timer-based REST polling as a fallback or supplement to SSE — the correct recovery on SSE error is backoff → one-shot REST re-fetch → reopen `EventSource`. **Exception**: the `/workshops` dashboard is intentionally REST-only (it reads live Kubernetes state directly, not SAQ/DB state), so no SSE/polling rules apply there.
- **SSE connections are capped**: `MAX_SSE_CONNECTIONS` (default 200) is enforced via the `sse_capacity_guard` dependency in `backend/soundcheck/routes/_sse.py`, which 503s new connections once the semaphore is exhausted. Don't remove or bypass this guard.
- **Two-tier `readyz` check**: Tier 1 fetches `ui-config.yml`/`zero-touch-config.yml` and probes the tabs it declares; Tier 2 is a legacy Antora fallback (probes root + `/content/`) used only when Tier 1 finds no config. Tabs support `initial_state: active|deferred|skip` — `deferred` failures don't count toward health status, `skip` tabs are never probed.

## Conventions

- Env vars are parsed **only** in `backend/soundcheck/config.py` (a `pydantic-settings` `Settings` model); every other module imports the resulting constant. Don't read `os.environ` elsewhere.
- FastAPI's `get_db()` rolls back on exception but does **not** auto-commit — routes must explicitly commit after writes.
- Frontend uses Svelte 5 runes exclusively (`$state`, `$derived`, `$effect`, `$props`) — no legacy `$:` reactive statements or `svelte/store`. `$app/state` (not `$app/stores`) is the SvelteKit import to use.
- `.svelte.ts` files are runes-enabled shared state modules (e.g. `checkStatuses.svelte.ts`), distinct from plain `.ts` utility files.

## Testing (current state — don't assume more exists)

- Backend: `backend/tests/test_config.py` is currently the **only** test file (covers `config.py` settings parsing). No `conftest.py`, no fixtures, no route/service/task tests yet. `pytest` is already a `dev` optional-dependency in `pyproject.toml`.
- Frontend: no test suite exists yet (no Vitest/Playwright config, no `tests/` directory).
- See `.cursor/prompts/backend-testing.md` / `frontend-testing.md` for the plan to build these out.

## Security

- `ALLOWED_URL_PATTERNS` (hostname allowlist, required env var) is soundcheck's SSRF guard for outbound health-check requests — don't add code paths that fetch arbitrary user-supplied URLs without going through it.
- `CORS_ORIGINS` containing `*` is rejected at startup by a validator in `config.py` (unsafe combined with `allow_credentials=True`) — don't work around this.
- In any `ENVIRONMENT` other than `development`, startup fails closed (`RuntimeError`) if neither `POSTGRES_PASSWORD` nor `DATABASE_URL` is set — don't reintroduce a silent default-credentials fallback for non-dev environments.
