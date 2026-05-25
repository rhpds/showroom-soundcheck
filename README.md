# Showroom Soundcheck

Session-based health check tool for showroom environments. Resolves Babylon GUIDs, workshops, and resource pools to showroom URLs and runs async health checks with live-streamed results.

---

## Quick Start

```bash
podman compose up -d   # or: docker compose up -d
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| SAQ monitor | http://localhost:8080 |

---

## User Guide

### Creating Sessions

From the UI at `/sessions/new`, provide one of:

- **URLs** — direct showroom URLs to check
- **GUID** — Babylon ResourceClaim provision GUID
- **Workshop GUID** — Babylon workshop GUID
- **Resource Pool** — Babylon resource pool name

### Deep-Link Creation

Create sessions via URL by navigating to `/check` with query parameters:

```
/check?urls=https://showroom1.example.com,https://showroom2.example.com
/check?guid=abc12
/check?workshop=9ucgv5
/check?pool=my-pool
/check?guid=abc12&cluster=east&type=healthz&name=My+Session
```

| Parameter  | Description |
|------------|-------------|
| `urls`     | Comma-separated showroom URLs |
| `guid`     | Babylon ResourceClaim provision GUID |
| `workshop` | Babylon workshop GUID |
| `pool`     | Babylon resource pool name |
| `type`     | `readyz` (default) or `healthz` |
| `name`     | Optional session label |
| `cluster`  | Babylon cluster name (searches all if omitted) |

At least one of `urls`, `guid`, `workshop`, or `pool` is required.

### Groups

Groups are named collections of sources (GUIDs, workshops, pools) that can be run repeatedly. Each run creates child sessions for every source. Manage groups at `/groups`.

### Check Types

- **`readyz`** — Full readiness check (config, content pages, tabs)
- **`healthz`** — Liveness check (base URL reachability only)

---

## Developer Guide

### Local Development (without containers)

Requires PostgreSQL and Redis running locally.

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn soundcheck.main:app --reload --port 8000

# Workers (separate terminals)
saq soundcheck.worker.orchestration_settings --workers 1
saq soundcheck.worker.check_settings --workers 1

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Environment Variables

#### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | _(built from below)_ | Full Postgres URL (overrides individual vars) |
| `POSTGRES_USER` | `soundcheck` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `soundcheck_dev` | PostgreSQL password |
| `POSTGRES_DB` | `soundcheck` | Database name |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |

#### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis URL for SAQ + Pub/Sub |
| `CHECK_CONCURRENCY` | `20` | Max concurrent health checks per worker |
| `ORCHESTRATION_CONCURRENCY` | `10` | Max concurrent orchestration tasks |
| `VERIFY_SSL` | `true` | TLS verification for checks (compose defaults to `false`) |
| `ALLOWED_URL_PATTERNS` | _(none)_ | Comma-separated hostname globs for URL allowlist |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated CORS origins |
| `API_KEY` | _(empty)_ | If set, required via `X-API-Key` header for mutating requests |

#### Babylon

| Variable | Default | Description |
|----------|---------|-------------|
| `BABYLON_CLUSTERS` | `[]` | JSON array of kubeconfig paths; order = search priority |
| `BABYLON_CATALOG_URLS` | _(empty)_ | JSON object mapping cluster name to catalog UI base URL |
| `BABYLON_KUBECONFIG_DIR` | `./secrets` | Host directory mounted for kubeconfigs (compose only) |

Cluster names are derived from filenames by stripping `.kubeconfig` (and any leading `NN-` prefix). The legacy JSON object format is also accepted.

### Architecture

```
backend/soundcheck/
├── main.py                     # FastAPI entry point
├── config.py                   # Settings from env vars
├── database.py                 # Async SQLAlchemy session
├── models.py                   # SQLModel tables
├── schemas.py                  # Pydantic request/response models
├── utils.py                    # Input parsing, URL validation
├── worker.py                   # SAQ queue definitions
├── routes/
│   ├── sessions.py             # Session CRUD + SSE streaming
│   ├── groups.py               # Group CRUD + run management
│   ├── health.py               # /api/ping, /api/health, /api/config/clusters
│   └── check.py                # Deep-link /api/check redirect
├── services/
│   ├── check_service.py        # Two-tier health check logic
│   ├── babylon_service.py      # GUID/workshop/pool → URL resolution
│   ├── babylon_client.py       # K8s API client via kubeconfigs
│   └── session_service.py      # Session/group orchestration
└── tasks/                      # SAQ task handlers

frontend/src/                   # SvelteKit SPA + PatternFly 6
├── routes/
│   ├── sessions/               # Session list
│   ├── sessions/new/           # Create session form
│   ├── session/[id]/           # Session detail with live updates
│   ├── groups/                 # Group list + create
│   ├── group/[id]/             # Group management + run history
│   └── check/                  # Deep-link redirect
└── lib/
    ├── api.ts                  # Typed API client
    ├── types.ts                # TypeScript types
    └── components/             # Shared UI components
```

### Two-Tier Readiness Check (`readyz`)

**Tier 1 (nookbag-style):** Fetches `ui-config.yml` (or `zero-touch-config.yml`) from the showroom, parses it, probes the Antora content URLs and tab URLs for reachability and iframe-blocking headers.

**Tier 2 (legacy Antora fallback):** If Tier 1 finds no config on a non-nookbag showroom, falls back to probing the root URL and `/content/` path.

Both tiers retry failed requests (2 retries with linear backoff).

### Database

Five tables: `sessions`, `session_targets`, `check_results`, `session_groups`, `group_runs`. Migrations are managed via Alembic and run automatically on container startup via `backend/entrypoint.sh`.

### Linting

```bash
make lint       # ruff + eslint + svelte-check
make format     # ruff format + prettier
make check      # lint + format-check
```

### Container Images

| Image | Pull URL |
|-------|----------|
| Backend  | `quay.io/rhpds/showroom-soundcheck-backend` |
| Frontend | `quay.io/rhpds/showroom-soundcheck-frontend` |

Built and pushed on tagged releases (`v*`) via GitHub Actions. Each release produces `latest` plus semver tags (e.g. `v1.0.0`, `v1.0`, `v1`).

### OpenShift Deployment

See `deploy/` directory for Kubernetes/OpenShift manifests.

### Standalone URL Discovery Script

For users with `oc` CLI access to a Babylon cluster:

```bash
./scripts/showroom-urls.sh -w <workshop-guid>
./scripts/showroom-urls.sh -r <rc-guid>
./scripts/showroom-urls.sh -w <workshop-guid> -n <namespace>
```

Requires `oc` (logged in) and `jq`. Run `./scripts/showroom-urls.sh -h` for full usage.
