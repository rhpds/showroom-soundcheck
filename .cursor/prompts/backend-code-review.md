# Backend Code Review Agent Prompt

You are an expert Python backend code reviewer specializing in **FastAPI**, **SQLModel/SQLAlchemy async**, **SAQ (Simple Async Queue)**, **Redis**, **asyncio**, and **production-grade API design**. Your task is to perform a thorough, multi-dimensional code review of the Showroom Soundcheck backend located at `backend/soundcheck/`.

## Codebase Overview

This is a FastAPI application that performs health checks against "showroom" environments (educational lab UIs on OpenShift). Key characteristics:

- **Framework**: FastAPI + Uvicorn ASGI
- **Task Queue**: SAQ (Simple Async Queue) >=0.26 with Redis backend -- two separate queues (orchestration + checks)
- **Pub/Sub**: Redis Pub/Sub for real-time SSE event delivery
- **ORM**: SQLModel + SQLAlchemy 2.x async with asyncpg
- **Migrations**: Alembic (async)
- **HTTP Client**: httpx (for health probes and Kubernetes API calls)
- **Database**: PostgreSQL (async via asyncpg)
- **Cache/Broker**: Redis (hiredis accelerated)
- **Logging**: Structured JSON logging via python-json-logger (configurable via `LOG_FORMAT` env var)
- **Python**: >=3.12

### Architecture

```
soundcheck/
+-- main.py              # FastAPI app, lifespan, CORS, X-Request-ID middleware, API key guard, global exception handler, router includes
+-- config.py            # Env-var config: DB URLs, pool sizing, REDIS_URL, concurrency, CORS_ORIGINS, API_KEY, LOG_FORMAT
+-- database.py          # Async engine, session factory, DbSession dependency (pool sizing configurable via env vars)
+-- models.py            # SQLModel table models, FK constraints with ON DELETE CASCADE, JSON/JSONB columns
+-- schemas.py           # Pydantic request/response schemas
+-- utils.py             # GUID extraction, URL allowlist (SSRF), input validation
+-- worker.py            # SAQ queue definitions, lifecycle hooks, settings dicts, worker logging config
+-- tasks/
|   +-- __init__.py      # TaskContext TypedDict for typed SAQ worker ctx
|   +-- orchestration.py # Coordinator tasks: run_session_checks, run_group, run_single_source, sync_metadata, sweep_stale_sessions
|   +-- checks.py        # Leaf task: check_target (individual HTTP health checks)
|   +-- events.py        # Redis Pub/Sub helpers: publish_session_event, publish_group_event
+-- routes/
|   +-- health.py        # GET /ping, /health, /config/clusters
|   +-- check.py         # GET /check (deep-link session creation)
|   +-- sessions.py      # Session CRUD, clone, run (enqueue via SAQ), pin, SSE streaming
|   +-- groups.py        # Group CRUD, members, run (enqueue via SAQ), sync-metadata, pin
|   +-- workshops.py     # Workshop dashboard: list/filter Workshop CRDs across Babylon clusters (request/response, not SSE)
|   +-- _serializers.py  # Shared response serialization helpers
+-- services/
    +-- check_service.py  # Health check engine (single-target check logic)
    +-- session_service.py # Session/group DB orchestration
    +-- babylon_service.py # K8s GUID/Workshop/ResourcePool resolution (uses ResolvedEntry TypedDict)
    +-- babylon_client.py  # httpx K8s API client manager (async init)
```

### SAQ Worker Architecture

Background work uses SAQ with a two-queue design to prevent deadlocks:

- **`orchestration` queue**: Lightweight coordinators (`run_session_checks`, `run_group`, `run_single_source`, `sync_metadata`). These fan out child jobs via fire-and-forget `queue.enqueue()` and return immediately -- no task ever blocks waiting for children. Also runs a cron job (`sweep_stale_sessions` every 5 min).
- **`checks` queue**: Leaf tasks (`check_target`) -- individual HTTP health checks. High concurrency, no child dependencies. Each leaf task calls `_try_finalize_session()` after writing its result; the last target to complete triggers session (and possibly group) finalization.

Routes enqueue work via `await queue.enqueue("run_session_checks", session_id=sid, timeout=900)`. Workers publish progress events to Redis Pub/Sub channels (`session:{id}`), which the SSE endpoint in `routes/sessions.py` subscribes to for real-time streaming.

**Fan-out and finalization pattern**: Orchestrators don't use `queue.map()` or `queue.apply()`. Instead they enqueue N fire-and-forget jobs. Each leaf job, upon completion, calls `_try_finalize_session()` which checks if all siblings are done. The last sibling to complete triggers session finalization and cascades to group finalization if applicable.

### Workshop Dashboard (routes/workshops.py)

A newer module providing real-time visibility into Workshop CRDs across all configured Babylon clusters. Unlike session/group routes that use SSE streaming via Redis Pub/Sub, workshops serves data via standard request/response because it reads directly from Kubernetes APIs rather than from SAQ-driven DB state. Supports filtering by cluster, status, white-glove flag, and time window. Uses `asyncio.gather(*tasks, return_exceptions=True)` for concurrent multi-cluster K8s API calls.

## Review Dimensions

For each dimension below, examine every relevant file and provide:
1. **Specific findings** with file paths and line references
2. **Severity** (Critical / High / Medium / Low / Info)
3. **Concrete fix recommendations** with code examples where helpful

---

### 1. Security

Review against OWASP and production security standards:

- **CORS configuration**: `main.py` uses `CORS_ORIGINS` from `config.py` (defaults to `http://localhost:5173`, configurable via env var as comma-separated list). Verify that production deployments set `CORS_ORIGINS` to the actual frontend domain(s). The middleware uses `allow_credentials=True` -- ensure no wildcard `*` is configured alongside credentials in any environment.

- **SSRF protection**: `utils.py` has `ALLOWED_URL_PATTERNS` allowlist using `fnmatch` glob matching against hostnames. Verify this is comprehensive -- check for bypass vectors (IP addresses, DNS rebinding, URL encoding tricks, scheme handling).

- **Input validation**: Check all user-supplied inputs across routes. Look at `parse_check_params()`, the `SessionCreate`/`GroupCreate` schemas, and query parameters. Are there missing length limits, regex validation on GUIDs, or unvalidated string fields stored directly? The `X-Request-ID` header is validated against a strict regex (`^[a-zA-Z0-9._:/-]{1,128}$`) to prevent log injection -- verify this is applied consistently.

- **SQL injection**: While SQLModel/SQLAlchemy parameterize queries, check for any raw SQL or string interpolation in queries.

- **Secret handling**: Check `config.py` for hardcoded defaults (e.g., `soundcheck_dev` password -- a warning is logged at startup via `warn_default_credentials()` but the app does not refuse to start). Check `babylon_client.py` for token/certificate handling and temp file cleanup for client certs.

- **Error information leakage**: A global exception handler in `main.py` catches unhandled errors and returns a generic `{"detail": "Internal server error", "request_id": "..."}` response. Verify no other path leaks stack traces, internal paths, or sensitive configuration to API callers.

- **Authentication/Authorization**: Mutating requests require an `X-API-Key` header when the `API_KEY` env var is set (middleware in `main.py`). Evaluate whether a single shared key is sufficient for production (no per-user identity, no revocation, no audit trail). All GET routes including SSE streams and the workshops dashboard are unauthenticated. Is this acceptable for the deployment model?

- **SAQ web monitor**: The SAQ web UI is mounted at `/monitor` without any authentication guard (`saq.web.starlette.saq_web`). Verify whether this exposes sensitive job data (payloads, error messages, Redis connection info) and whether it should be restricted or removed in production.

---

### 2. SAQ Worker & Async/Concurrency Patterns

Review the SAQ task queue architecture and async code for correctness:

- **Two-queue deadlock prevention**: The separation into `orchestration` and `checks` queues prevents deadlocks where orchestrators wait on children. Verify that no task on the `checks` queue enqueues work back onto the same queue (circular dependency). Check that all `enqueue()` calls target the correct queue (orchestration tasks enqueue checks to `checks_queue`, group tasks enqueue sessions to `orchestration_queue`).

- **Task idempotency**: SAQ tasks may be retried on worker crash. Verify that `run_session_checks`, `check_target`, and `run_group` are safe to re-execute (e.g., `mark_session_running()` returns False if already running to prevent double-execution; `check_target` deletes existing `CheckResult` before writing -- are there race conditions?).

- **Fire-and-forget fan-out with last-writer-finalizes pattern**: Orchestration tasks enqueue N individual check jobs and return immediately. Each `check_target` leaf task calls `_try_finalize_session()` on completion -- the last sibling to finish triggers session finalization. Review: what happens if a check_target job is lost (timeout/crash) and never calls `_try_finalize_session()`? Does `sweep_stale_sessions` cover this case? Is there a window where all checks complete but finalization races?

- **Task timeout configuration**: Individual `enqueue()` calls set `timeout=300` (check_target) or `timeout=900` (run_session_checks). These are SAQ job-level timeouts. Evaluate whether these are appropriate. What happens when a timeout fires mid-check -- the session remains in "running" until `sweep_stale_sessions` runs (every 5 min, max_age_minutes=30).

- **Worker lifecycle hooks**: `_orchestration_startup` calls `babylon_client._default_manager.init_clients_async()` (async-safe, non-blocking). Check that `_orchestration_shutdown` properly awaits cleanup before the worker exits.

- **Concurrency settings**: `CHECK_CONCURRENCY` (default 20) and `ORCHESTRATION_CONCURRENCY` (default 10) control SAQ worker parallelism. Evaluate whether these defaults are appropriate given the DB connection pool size (`DB_POOL_SIZE` default 10, `DB_MAX_OVERFLOW` default 20, configurable via env vars). Can 20 concurrent check tasks exhaust the pool?

- **Redis connection management**: Both queues create Redis connections via `Queue.from_url()`. Verify connection pooling is configured, connections are reused across tasks, and reconnection is handled on transient Redis failures.

- **Event loop blocking**: Check for any synchronous/blocking calls inside `async def` task functions (file I/O, `yaml.safe_load`, DNS lookups, `json.loads` on large payloads).

- **SSE streaming via Redis Pub/Sub**: `routes/sessions.py` and `routes/groups.py` subscribe to `session:{id}` and `group:{id}` Redis Pub/Sub channels, streaming updates to the browser via `EventSourceResponse`. Task functions publish events through `tasks/events.py` helpers (`publish_session_event`, `publish_group_event`). Evaluate: connection cleanup on client disconnect, what happens if Redis is temporarily unavailable, and whether the subscription properly unsubscribes on exit.

- **SAQ retry configuration**: SAQ supports per-job retry via `retries`, `retry_delay`, and `retry_backoff` parameters on `enqueue()`. Verify whether any enqueue calls use retries. A previous attempt to configure retries at the worker level was reverted as invalid (retries are job-level in SAQ). Evaluate whether leaf check tasks should use `retries=N` for transient HTTP failures.

---

### 3. Streaming-First Architecture (SSE + Async -- No Polling)

This application is intentionally built around **fire-and-forget requests + SSE push updates**. The entire data flow is: REST POST enqueues SAQ job -> worker publishes progress via Redis Pub/Sub -> SSE endpoint streams to browser EventSource. **Any pattern that degrades this to polling is a regression.** Review for:

- **No polling endpoints**: Verify no route is designed to be called repeatedly on a timer by the frontend. Routes should return current state on demand (for initial load or recovery) but should NOT be the primary mechanism for tracking progress. Progress comes via SSE. Note: `routes/workshops.py` is an exception -- it serves K8s API data via request/response because it does not use SAQ/DB state. Evaluate whether caching or SSE should be added there as usage scales.

- **SSE event granularity**: Workers should publish granular, incremental events (`target_update`, `session_running`, `session_complete`) -- not "fetch the whole session" events that force the client to re-query REST. Check that `tasks/events.py` publishes enough detail for the frontend to update in place without additional REST calls.

- **No synchronous waiting in routes**: Mutating routes (`POST /sessions`, `POST /groups/{id}/run`) must enqueue SAQ jobs and return immediately (`201`/`200`). Flag any route that `await`s task completion or blocks until checks finish -- this defeats the async architecture and creates timeout risk.

- **Redis Pub/Sub reliability**: Events are fire-and-forget on the publisher side. If the SSE client connects after events were already published (race condition), the client must be able to recover by re-fetching current state via REST and then reconnecting SSE. Verify the SSE endpoints handle this (e.g., sending an initial state snapshot on connect, or the frontend handles it).

- **No `time.sleep()` or busy-wait patterns**: In async task functions, all delays must use `asyncio.sleep()`, never `time.sleep()` which blocks the event loop. Flag any `while True` + sleep loops that effectively poll for state changes instead of using proper async coordination (events, callbacks, Pub/Sub).

- **Backpressure and connection limits**: SSE endpoints hold a long-lived connection + Redis subscription per connected client. Evaluate whether there is any limit on concurrent SSE connections, and what happens if a client connects but never reads (slow consumer).

---

### 4. Database & ORM Patterns

Review SQLModel/SQLAlchemy usage:

- **Connection pool sizing**: `database.py` uses `DB_POOL_SIZE` (default 10) and `DB_MAX_OVERFLOW` (default 20), configurable via env vars. `DB_POOL_RECYCLE` is set to 3600s. SAQ workers create their own sessions via `async_session_factory` (injected during worker startup). With `CHECK_CONCURRENCY=20` concurrent check tasks each opening a session, evaluate whether the pool is adequate. Note: each SAQ worker process has its own pool -- verify the total connections across API server + orchestration worker + check worker(s) do not exceed PostgreSQL's `max_connections`.

- **Transaction management**: `get_db()` rolls back on exception but does NOT commit on success -- routes must explicitly commit. Check all routes for missing commits, especially the member add/remove and pin toggle operations.

- **JSON-in-string columns**: Some model fields store data as JSON strings (`source_urls`, `source_guids`, `member_metadata`). Note that `CheckResult.detail` has been converted to a native JSON column. Evaluate whether the remaining string-encoded JSON fields should also use PostgreSQL JSONB for queryability and type safety.

- **FK constraints**: Tables use FK constraints with ON DELETE CASCADE. Verify cascades are appropriate (e.g., deleting a session cascading to results is correct, but verify no unintended data loss paths exist).

- **N+1 queries**: Check `get_group()` in `groups.py` and `fetch_session_data()` for potential N+1 patterns. Are there opportunities to use `selectinload()` or joined queries?

- **Missing indexes**: Review query patterns (e.g., `CheckSession.group_run_id`, `CheckResult.target_id`) against the declared indexes on models.

- **`Optional[int]` primary keys**: All models use `id: Optional[int] = Field(default=None, primary_key=True)`. This is a known SQLModel pattern but can be confusing -- instances returned from DB will always have `id` set.

- **Engine created at import time**: `database.py` creates the engine at module load. If env vars are not set yet (e.g., during testing), this fails eagerly. Evaluate lazy initialization.

---

### 5. Error Handling & Resilience

- **Inconsistent error handling**: `check.py` `check_redirect()` silently returns `session_id=""` on validation errors instead of raising HTTP 422. Compare with `sessions.py` `create_session()` which raises HTTP 422. Is this intentional?

- **SAQ task failures and stale sessions**: If `run_session_checks` raises after marking the session as "running", `_mark_session_failed()` is called in the except block. If the entire worker crashes, the session remains stuck. The `sweep_stale_sessions` cron job (every 5 min, max_age_minutes=30) acts as a safety net. Verify coverage: does it catch all stuck states including orphaned group runs? What is the user experience during the 30-minute window before cleanup?

- **K8s client failures**: `babylon_client.py` catches exceptions broadly in `init_clients_async()` but continues without the failed cluster. Is this logged clearly enough? Are retries appropriate?

- **Missing HTTP status codes on response models**: Routes like `toggle_pin`, `run_group`, `add_member` return plain dicts without `response_model`. Should these have explicit schemas?

- **Workshop route error handling**: `routes/workshops.py` makes concurrent K8s API calls across multiple clusters via `asyncio.gather(*tasks, return_exceptions=True)`. Verify that failures in one cluster do not crash the entire response, and that timeouts are reasonable.

---

### 6. Code Quality & Maintainability

- **DRY violations**: Check whether `_serializers.py` fully consolidates the previously duplicated `_session_to_list_item()` and `_target_to_public()` helpers, or if duplication remains between routes.

- **Task module organization**: Task functions are split into `tasks/orchestration.py` (coordinators) and `tasks/checks.py` (leaf tasks), with shared Pub/Sub helpers in `tasks/events.py` and a `TaskContext` TypedDict in `tasks/__init__.py`. Verify this separation is clean -- no circular imports between task modules, no task function logic leaking into `worker.py` (which should only define queues, lifecycle hooks, and settings dicts).

- **Duplicate config parsing**: Verify `CHECK_CONCURRENCY`, `ORCHESTRATION_CONCURRENCY`, `VERIFY_SSL`, `LOG_FORMAT`, and `REDIS_URL` are parsed only in `config.py` and imported elsewhere -- no duplicate env var reads.

- **Type safety**: Several functions return `dict[str, str]` or `dict[str, Any]` where dataclasses or TypedDicts would provide better IDE support and catch errors. The `TaskContext` TypedDict in `tasks/__init__.py` types the SAQ worker context -- verify all task functions use it consistently and do not access untyped keys from `ctx`. Check that `ResolvedEntry` TypedDict in `babylon_service.py` is used consistently for resolution results.

- **Unused imports**: Check for any unused imports across all files.

- **Workshop route size**: `routes/workshops.py` is a large module (~768 lines). Evaluate whether it should be split (e.g., K8s fetching logic into a service, Pydantic models into schemas).

---

### 7. API Design

- **REST conventions**: Evaluate HTTP method choices. `POST /sessions/{id}/run` semantically duplicates `POST /sessions/{id}/clone`. Are both needed? `DELETE /groups/{id}/members` uses a request body, which is technically allowed but unconventional for DELETE. (Note: `DELETE /sessions/{id}/sources/{source}` was refactored to use path params.)

- **Pagination**: `load_all_sessions()` and `load_all_groups()` hardcode `limit(100)`. There is no cursor/offset pagination support. Will this scale?

- **Response consistency**: Some endpoints return `response_model` schemas, others return bare dicts (`{"status": "started"}`). Standardize.

- **SSE endpoint**: `stream_session()` yields Pydantic models via `EventSourceResponse`. Verify this serializes correctly and handles backpressure.

- **Missing endpoints**: No DELETE for sessions or groups. No bulk operations. Is session/group cleanup handled elsewhere?

- **Workshop API design**: `GET /api/workshops` returns all workshops across clusters with query param filtering. Evaluate whether this will scale (N clusters x M workshops per cluster) and whether pagination, caching, or server-side aggregation limits are needed.

---

### 8. Configuration & Deployment

- **Default credentials**: `config.py` defaults to `soundcheck_dev` password when `POSTGRES_PASSWORD` and `DATABASE_URL` are not set. A warning is logged at startup (`warn_default_credentials()`), but the app does NOT refuse to start. Evaluate whether production deployments should fail-closed instead.

- **`entrypoint.sh`**: Runs `alembic upgrade head` before every start. This is common but risky in multi-replica deployments -- concurrent migration runs can deadlock. Consider a migration job pattern.

- **Worker deployment**: The SAQ worker requires a separate process (`saq soundcheck.worker.orchestration_settings` and `saq soundcheck.worker.check_settings`). Verify the deployment manifests (Dockerfile, docker-compose, k8s) start both workers alongside the API server. Check that worker processes have appropriate resource limits and health checks.

- **Redis availability**: Redis is a hard dependency (SAQ queue + Pub/Sub). Evaluate: what happens if Redis is unavailable at startup? Is there a health check that verifies Redis connectivity? Are there reconnection strategies configured?

- **`REDIS_URL` configuration**: Default is `redis://localhost:6379`. For production, verify TLS (`rediss://`), auth, and database index are configurable.

- **Uvicorn configuration**: `entrypoint.sh` runs a single Uvicorn worker with no `--workers` flag (a previous attempt to add `UVICORN_WORKERS` was reverted). For production, multiple workers or a Gunicorn wrapper would be appropriate -- but note that SSE connections are per-process, which complicates multi-worker deployments.

- **Health check depth**: `/health` and `/ping` both return `{"status": "ok"}` without checking DB connectivity, Redis connectivity, or downstream service health. For Kubernetes liveness/readiness probes, the health endpoint should verify critical dependencies.

- **SAQ monitoring**: The SAQ web UI is mounted at `/monitor` (with a fallback no-op if the import fails). Verify whether this should be behind auth or only exposed in non-production environments. Check if job retention/cleanup is configured to prevent Redis memory growth.

---

### 9. Testing & Observability

- **No test suite**: There are no test files (`test_*.py`, `conftest.py`, `pytest.ini`). Assess what testing strategy would be most impactful. SAQ tasks should be unit-testable by mocking the `ctx` dict (with `session_factory` and `redis`). Integration tests for routes should verify jobs are enqueued correctly.

- **Logging**: Structured JSON logging is available via `LOG_FORMAT=json` env var (using `pythonjsonlogger.json.JsonFormatter`). Both the API server (`main.py`) and SAQ workers (`worker.py`) configure logging independently. Verify: are log formats consistent between API and workers? Do worker logs include job IDs for traceability? Is the `request_id` field propagated into SAQ job context for end-to-end tracing?

- **Request tracing**: An `X-Request-ID` middleware generates or validates a correlation ID per request and returns it in the response header. Evaluate whether this ID is propagated into SAQ job kwargs so that worker logs can be correlated back to the originating API request across the full pipeline (API -> SAQ queue -> worker -> Redis Pub/Sub -> SSE).

- **No metrics**: There is no Prometheus metrics endpoint, no request timing middleware, no counter for health check results. SAQ provides job timing and queue depth metrics -- verify these are being exposed or logged. What observability instrumentation would be highest value?

- **SAQ dead letter / retry visibility**: When tasks fail or timeout, verify there is a way to inspect failed jobs (SAQ web UI at `/monitor`, logging, or alerting). Stale "running" sessions with no active SAQ job indicate lost work -- the `sweep_stale_sessions` cron job should catch these.

---

## Output Format

Structure your review as follows:

### Issue Summary Table

Start with a table of **all** findings, ordered from most to least critical. Every row must include a sequential number, severity, the review section it falls under, a short title, and the file(s) affected.

| # | Severity | Section | Finding | File(s) |
|---|----------|---------|---------|---------|
| 1 | Critical | Security | SAQ monitor exposed without auth | `main.py` |
| 2 | High | Concurrency | Lost check_target leaves session stuck for 30min | `tasks/checks.py`, `tasks/orchestration.py` |
| ... | ... | ... | ... | ... |

Use these severity levels in order: **Critical -> High -> Medium -> Low -> Info**.

### Executive Summary
A 3-5 sentence overview of the codebase health, highlighting the most critical issues.

### Detailed Findings

For each finding from the table above (in the same order), provide:
- File path and line references
- Detailed explanation of the issue
- Concrete fix recommendation with code examples where helpful

### Recommended Priority Order
A numbered list of the top 10 changes ordered by impact-to-effort ratio.

### Positive Observations
Note things the codebase does well -- good patterns worth preserving.
