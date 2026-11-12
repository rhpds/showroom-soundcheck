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
- **SSE keepalives are the framework's job**: these routes use `fastapi.sse.EventSourceResponse` (FastAPI's native SSE, not `sse-starlette`), and FastAPI's routing layer already emits a `: ping` comment whenever the generator has been idle for `fastapi.sse._PING_INTERVAL` (15s). Don't hand-roll a per-route heartbeat timer on top of it. If 15s is ever too slow for a proxy in front of us, override that one interval centrally and record the timeout being targeted.
- **Two-tier `readyz` check**: Tier 1 fetches `ui-config.yml`/`zero-touch-config.yml` and probes the tabs it declares; Tier 2 is a legacy Antora fallback (probes root + `/content/`) used only when Tier 1 finds no config. Tabs support `initial_state: active|deferred|skip` — `deferred` failures don't count toward health status, `skip` tabs are never probed. Tabs also support `accepted_status_codes: [<int>, ...]` — a per-tab allowlist of additional non-2xx status codes (e.g. `403` from an SSO/oauth-proxy login page) to treat as a successful probe; see README's "Tab `accepted_status_codes`" section.
- **QA-automation healthcheck probe**: independent of (and run concurrently with) the tier1/tier2 logic above. `check_qa_healthcheck()` in `check_service.py` is the single integration point — it probes `GET {url}/runner/api/config` (falling back to unprefixed `/api/config`; the `/runner/` prefix is what nginx actually fronts the sidecar's `/api/*` routes with on real showrooms — confirmed live, don't revert to bare `/api/config` as primary) for a `"qa"` → `"healthcheck"` stage (a runtime-automation sidecar feature; see README's "QA Automation Healthcheck" section), and if present, runs it via `GET {url}/stream/qa/healthcheck` (SSE, unprefixed — that one *is* mounted at the root). Absence is never a failure; a present-but-failing/timed-out/erroring run is. No DB/task/route changes are needed to add further behavior here — `tasks/checks.py` just calls `check_single_target()`, which already merges this in.

## Conventions

- **Idempotent get-or-create takes an advisory lock.** `get_or_create_session_for_workshop_guid` and `get_or_create_group` in `session_service.py` both run `SELECT pg_advisory_xact_lock(hashtext(:key))` *before* the lookup, so concurrent callers resolving the same key serialize instead of all missing the SELECT and all inserting; the lock releases with the request's transaction. Both return `(obj, created)` so the route knows whether to enqueue follow-up work and whether to answer 201 or 200.
- **Group creation is idempotent on content, not on an opaque key.** `POST /api/groups` hashes `(name, guids, workshop_guids, resource_pools, babylon_cluster)` into `SessionGroup.content_hash` (`session_service.compute_content_hash`) and reuses the oldest group with a matching hash unless the caller sends `force_create: true`. The hash is **not** a uniqueness constraint — it only short-circuits matching duplicates — so `content_hash` is a plain indexed column, not `UNIQUE`, and pre-existing duplicate groups stay legal. Any route that mutates `name` or the source lists or `babylon_cluster` on an existing group (`rename_group`, `add_source`, `remove_source`) **must** call `session_service.refresh_content_hash(grp)` before committing, or that group silently stops matching future identical create requests.
- Env vars are parsed **only** in `backend/soundcheck/config.py` (a `pydantic-settings` `Settings` model); every other module imports the resulting constant. Don't read `os.environ` elsewhere.
- FastAPI's `get_db()` rolls back on exception but does **not** auto-commit — routes must explicitly commit after writes.
- Frontend uses Svelte 5 runes exclusively (`$state`, `$derived`, `$effect`, `$props`) — no legacy `$:` reactive statements or `svelte/store`. `$app/state` (not `$app/stores`) is the SvelteKit import to use.
- `.svelte.ts` files are runes-enabled shared state modules (e.g. `checkStatuses.svelte.ts`), distinct from plain `.ts` utility files.

## Testing (current state — don't assume more exists)

- Backend: two test files exist — `backend/tests/test_config.py` (covers `config.py` settings parsing) and `backend/tests/test_check_service_qa.py` (covers the qa-automation healthcheck probe in `check_service.py`). No `conftest.py`, no fixtures, no route/service/task tests beyond those. `pytest` and `pytest-asyncio` are already `dev` optional-dependencies in `pyproject.toml`, with `asyncio_mode = "auto"` set.
- `test_check_service_qa.py` is the pattern to follow for new backend tests: `httpx.MockTransport` instead of real network calls, tests grouped in classes per function under test, and docstrings that record *why* a behaviour is expected (e.g. the `/runner/` prefix rationale) rather than restating the assertion.
- Frontend: no test suite exists yet (no Vitest/Playwright config, no `tests/` directory).
- See `.cursor/prompts/backend-testing.md` / `frontend-testing.md` for the plan to build these out.

## Security

- `ALLOWED_URL_PATTERNS` (hostname allowlist, required env var) is soundcheck's SSRF guard for outbound health-check requests — don't add code paths that fetch arbitrary user-supplied URLs without going through it.
- `CORS_ORIGINS` containing `*` is rejected at startup by a validator in `config.py` (unsafe combined with `allow_credentials=True`) — don't work around this.
- In any `ENVIRONMENT` other than `development`, startup fails closed (`RuntimeError`) if neither `POSTGRES_PASSWORD` nor `DATABASE_URL` is set — don't reintroduce a silent default-credentials fallback for non-dev environments.
