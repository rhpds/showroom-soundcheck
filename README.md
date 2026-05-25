# Showroom Soundcheck

Session-based health check tool for showroom environments. Supports direct URL checks and Babylon GUID discovery.

---

## User Guide

### Web App

The web app is available at your deployment's endpoint (e.g. `https://soundcheck.example.com`). From there you can:

- **Create sessions** using the landing page form (provide URLs, GUIDs, or Workshop GUIDs)
- **View session results** at `/session/<uuid>` — each session has a unique shareable URL
- **Browse session history** in the sidebar, grouped by date

#### Creating Sessions via URL

You can create sessions by navigating directly to `/check` with query parameters. This is useful for linking from external systems.

```
/check?urls=https://showroom1.example.com,https://showroom2.example.com
/check?guid=abc12,def34
/check?workshop=9ucgv5
/check?guid=abc12&cluster=east
/check?guid=abc12&type=healthz&name=My+Workshop
/check?urls=https://showroom1.example.com&mode=showroom
```

| Parameter  | Values                    | Description                                                         |
|------------|---------------------------|---------------------------------------------------------------------|
| `urls`     | comma-separated URLs      | Showroom URLs to check directly                                     |
| `guid`     | comma-separated strings   | Babylon ResourceClaim provision GUIDs                               |
| `workshop` | comma-separated strings   | Babylon Workshop GUIDs                                              |
| `type`     | `readyz` \| `healthz`     | Check type (default: `readyz`)                                      |
| `mode`     | `manual` \| `showroom`    | Check mode (default: `manual`)                                      |
| `name`     | string                    | Optional session label                                              |
| `cluster`  | string                    | Babylon cluster name — optional, searches all in priority order if omitted |

At least one of `urls`, `guid`, or `workshop` is required. If none are provided, you are redirected to `/`.

### Check Modes

- **`manual`** — Performs local nookbag-style checks directly (Tier 2 only). Use when the showroom has no health sidecar.
- **`showroom`** — Delegates to the showroom's `/readyz` or `/healthz` sidecar first (Tier 1). Falls back to local checks (Tier 2) if the sidecar is unavailable.

### Check Types

- **`readyz`** — Full readiness check (config, content, tabs).
- **`healthz`** — Liveness check.

---

## Developer Guide

### Quick Start

```bash
# Start the web app and database
podman compose up -d

# App + API: http://localhost:8000
# API docs:  http://localhost:8000/docs
```

### Local Development (without containers)

Requires a running PostgreSQL instance. Set `DATABASE_URL` or individual `POSTGRES_*` env vars.

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn soundcheck.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Environment Variables

| Variable               | Default              | Description                                                  |
|------------------------|----------------------|--------------------------------------------------------------|
| `DATABASE_URL`         | _(built from below)_ | Full Postgres connection URL (overrides individual vars)     |
| `POSTGRES_USER`        | `soundcheck`         | PostgreSQL username                                          |
| `POSTGRES_PASSWORD`    | `soundcheck_dev`     | PostgreSQL password                                          |
| `POSTGRES_DB`          | `soundcheck`         | Database name                                                |
| `POSTGRES_HOST`        | `localhost`          | PostgreSQL host                                              |
| `POSTGRES_PORT`        | `5432`               | PostgreSQL port                                              |
| `APP_PORT`             | `8000`               | App port (compose only)                                      |
| `CHECK_CONCURRENCY`    | `10`                 | Max concurrent health checks per session                     |
| `VERIFY_SSL`           | `true`               | TLS verification; set to `false`/`0`/`no` to disable (compose defaults to `false`) |
| `BABYLON_CLUSTERS`     | `[]`                 | JSON array of kubeconfig paths (order = search priority)     |
| `BABYLON_KUBECONFIG_DIR` | `./secrets`        | Host directory mounted for kubeconfigs                       |

#### Babylon Cluster Configuration

To enable GUID resolution, provide a JSON array of kubeconfig file paths. **Array order determines search priority** — when no cluster is specified, clusters are tried in order and the first match wins:

```json
["/secrets/west.kubeconfig", "/secrets/east.kubeconfig"]
```

Cluster names are derived from filenames by stripping the `.kubeconfig` extension (e.g. `east.kubeconfig` → `east`). Any leading `NN-` numeric prefix is also stripped if present.

Kubeconfig files are mounted from `BABYLON_KUBECONFIG_DIR` into `/secrets` in the container.

The legacy JSON object format (`{"east": "/secrets/east.kubeconfig"}`) is still accepted.

### Architecture

```
backend/soundcheck/           # FastAPI REST API
├── main.py                   # FastAPI app entry point (uvicorn)
├── config.py                 # Settings from env vars
├── database.py               # AsyncSession factory
├── models.py                 # SQLModel: CheckSession, SessionTarget, CheckResult, ...
├── schemas.py                # Pydantic request/response models
├── utils.py                  # Shared utilities: input parsing, GUID extraction, validation
├── routes/
│   ├── sessions.py           # Session CRUD + SSE streaming
│   ├── groups.py             # Group CRUD + run management
│   ├── health.py             # /api/ping, /api/health, /api/config/clusters
│   └── check.py              # Deep-link /api/check?... redirect
└── services/
    ├── check_service.py      # Async three-tier health check logic (no DB deps)
    ├── babylon_service.py    # GUID-to-URLs resolver (concurrent)
    ├── babylon_client.py     # K8s API client via kubeconfigs
    └── session_service.py    # Session/group orchestration

frontend/src/                 # SvelteKit SPA + PatternFly
├── routes/                   # File-based routing
│   ├── +page.svelte          # Landing page with check/group forms
│   ├── +layout.svelte        # App shell + sidebar
│   ├── session/[id]/         # Session detail page
│   ├── group/[id]/           # Group management page
│   └── check/                # Deep-link redirect
└── lib/
    ├── api.ts                # Typed API client
    ├── types.ts              # TypeScript types
    └── components/           # Sidebar, StatusBadge, TargetDetail
```

### Two-Tier Health Check Strategy

**Tier 1 (delegate):** Hits `{showroom_url}/readyz` or `/healthz`. If the nookbag health sidecar is running, it handles all checks and returns a comprehensive result.

**Tier 2 (local fallback):** If Tier 1 returns 404 or a connection error (no sidecar), Soundcheck performs checks itself:
1. Fetch `{showroom_url}/nookbag/ui-config.yml` (or `zero-touch-config.yml`)
2. Parse the config, resolve the Antora content URL, probe it
3. Resolve tab URLs from config, probe each for reachability and iframe-blocking headers

Both tiers retry failed requests (2 retries with linear backoff) before marking a target as unhealthy.

### Database

Five tables: `sessions`, `session_targets`, `check_results`, `session_groups`, `group_runs`. Migrations are managed via Alembic (`alembic upgrade head`) and run automatically on startup via `backend/entrypoint.sh`.

### Container Images

| Image | Pull URL |
|-------|----------|
| Backend  | `quay.io/rhpds/showroom-soundcheck-backend` |
| Frontend | `quay.io/rhpds/showroom-soundcheck-frontend` |

Images are built and pushed on tagged releases (`v*`) via GitHub Actions. A GitHub Release is also created automatically with auto-generated release notes and a table of the published image tags. Each release produces `latest` plus semver tags (e.g. `v1.0.0`, `v1.0`, `v1`).

### Standalone URL Discovery Script

For users who can `oc login` to a Babylon cluster directly but don't have kubeconfigs configured in Soundcheck:

```bash
./scripts/showroom-urls.sh -w <workshop-guid>           # by workshop GUID
./scripts/showroom-urls.sh -r <rc-guid>                  # by ResourceClaim provision GUID
./scripts/showroom-urls.sh -w <workshop-guid> -n <ns>    # limit to a namespace
```

Requires `oc` (logged in) and `jq`. Run `./scripts/showroom-urls.sh -h` for full usage.
