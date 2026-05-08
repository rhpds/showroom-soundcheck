# Showroom Soundcheck

Session-based health check tool for showroom environments. Supports direct URL checks, Babylon GUID discovery, and a CLI interface.

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

### CLI

The CLI is distributed as a container image (`quay.io/rhpds/showroom-soundcheck-cli`). It checks showroom URLs directly — no database or Babylon integration required.

> **Note:** Use `-t` (allocate a TTY) so the results table renders correctly. Without it, the container has no terminal and the table columns collapse.

```bash
# Check multiple showroom URLs
podman run --rm -t quay.io/rhpds/showroom-soundcheck-cli:latest \
  --urls https://showroom1.example.com,https://showroom2.example.com

# healthz (liveness) check instead of the default readyz (readiness)
podman run --rm -t quay.io/rhpds/showroom-soundcheck-cli:latest \
  --urls https://showroom1.example.com --check-type healthz

# Delegate to the showroom health sidecar first, fall back to local checks
podman run --rm -t quay.io/rhpds/showroom-soundcheck-cli:latest \
  --urls https://showroom1.example.com --check-mode showroom

# Skip TLS verification (e.g. self-signed certs)
podman run --rm -t quay.io/rhpds/showroom-soundcheck-cli:latest \
  --urls https://showroom1.example.com --insecure
```

| Option          | Description                                                              |
|-----------------|--------------------------------------------------------------------------|
| `--urls`        | **Required.** Comma-separated showroom URLs                              |
| `--check-type`  | `readyz` or `healthz` (default: `readyz`)                                |
| `--check-mode`  | `manual`, `showroom`, or `auto` (default: `manual`)                      |
| `-c`, `--concurrency` | Max concurrent checks (default: `10`, env: `CHECK_CONCURRENCY`)   |
| `--insecure`    | Disable TLS certificate verification (env: `VERIFY_SSL`)                 |
| `-v`, `--verbose` | Print detailed Tier 2 JSON results for each target                     |

**Exit codes:** `0` = all healthy, `1` = one or more unhealthy, `2` = invalid input.

### Check Modes

- **`manual`** — Performs local nookbag-style checks directly (Tier 2 only). Use when the showroom has no health sidecar.
- **`showroom`** — Delegates to the showroom's `/readyz` or `/healthz` sidecar first (Tier 1). Falls back to local checks (Tier 2) if the sidecar is unavailable.
- **`auto`** (CLI only) — Behaves the same as `showroom`.

### Check Types

- **`readyz`** — Full readiness check (config, content, tabs).
- **`healthz`** — Liveness check.

---

## Developer Guide

### Quick Start

```bash
# Start the web app and database
podman compose up -d

# UI:      http://localhost:3000
# Backend: http://localhost:8000
```

### Local Development (without containers)

Requires a running PostgreSQL instance. Set `DATABASE_URL` or individual `POSTGRES_*` env vars.

```bash
pip install -r requirements.txt
reflex init
reflex run --env dev
```

### Building the CLI Image

```bash
podman build -f Dockerfile.cli -t showroom-soundcheck-cli .
podman run --rm -t showroom-soundcheck-cli --urls https://showroom1.example.com
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
| `APP_PORT`             | `3000`               | Frontend port (compose only)                                 |
| `BACKEND_PORT`         | `8000`               | Backend API port (compose only)                              |
| `CHECK_CONCURRENCY`    | `10`                 | Max concurrent health checks per session                     |
| `VERIFY_SSL`           | `true`               | TLS verification; set to `false`/`0`/`no` to disable (compose defaults to `false`) |
| `REFLEX_ENV`           | `dev`                | `dev` enables auto-migrations; `prod` runs migrations only (compose hardcodes `dev`) |
| `BABYLON_CLUSTERS`     | `[]`                 | JSON array of kubeconfig paths (order = search priority)     |
| `BABYLON_KUBECONFIG_DIR` | `./secrets`        | Host directory mounted for kubeconfigs                       |

#### Babylon Cluster Configuration

To enable GUID resolution, provide a JSON array of kubeconfig file paths. **Array order determines search priority** — when no cluster is specified, clusters are tried in order and the first match wins:

```json
["/secrets/east.kubeconfig", "/secrets/west.kubeconfig"]
```

Cluster names are derived from filenames by stripping the `.kubeconfig` extension (e.g. `east.kubeconfig` → `east`). Any leading `NN-` numeric prefix is also stripped if present.

Kubeconfig files are mounted from `BABYLON_KUBECONFIG_DIR` into `/secrets` in the container.

The legacy JSON object format (`{"east": "/secrets/east.kubeconfig"}`) is still accepted.

### Architecture

```
soundcheck/
├── soundcheck.py         # Reflex app entry point
├── state.py              # SessionState: application state and event handlers
├── models.py             # SQLModel: CheckSession, SessionTarget, CheckResult
├── check_service.py      # Async two-tier health check logic (no DB deps)
├── babylon_service.py    # GUID-to-URLs resolver (concurrent)
├── babylon_client.py     # K8s API client via kubeconfigs
├── cli.py                # CLI entry point (showroom-soundcheck command)
├── utils.py              # Shared utilities: input parsing, GUID extraction, validation
├── styles.py             # Theme and component styles
├── pages.py              # Page definitions (home, session, check redirect)
└── components/
    ├── sidebar.py        # Session history sidebar
    ├── target.py         # Target row, status badges, detail dialog
    ├── session.py        # Session summary, targets list
    └── landing.py        # Landing page form
```

### Two-Tier Health Check Strategy

**Tier 1 (delegate):** Hits `{showroom_url}/readyz` or `/healthz`. If the nookbag health sidecar is running, it handles all checks and returns a comprehensive result.

**Tier 2 (local fallback):** If Tier 1 returns 404 or a connection error (no sidecar), Soundcheck performs checks itself:
1. Fetch `{showroom_url}/nookbag/ui-config.yml` (or `zero-touch-config.yml`)
2. Parse the config, resolve the Antora content URL, probe it
3. Resolve tab URLs from config, probe each for reachability and iframe-blocking headers

Both tiers retry failed requests (2 retries with linear backoff) before marking a target as unhealthy.

### Database

Three tables: `sessions`, `session_targets`, `check_results`. Migrations are managed via Reflex's database commands (`reflex db init`, `reflex db migrate`, `reflex db makemigrations`) which wrap Alembic. They run automatically on startup via `entrypoint.sh`.

### Container Images

| Image | Pull URL |
|-------|----------|
| Web app | `quay.io/rhpds/showroom-soundcheck-app` |
| CLI     | `quay.io/rhpds/showroom-soundcheck-cli` |

Images are built and pushed on tagged releases (`v*`) via GitHub Actions. A GitHub Release is also created automatically with auto-generated release notes and a table of the published image tags. Each release produces `latest` plus semver tags (e.g. `v1.0.0`, `v1.0`, `v1`).

### Standalone URL Discovery Script

For users who can `oc login` to a Babylon cluster directly but don't have kubeconfigs configured in Soundcheck:

```bash
./scripts/showroom-urls.sh -w <workshop-guid>           # by workshop GUID
./scripts/showroom-urls.sh -r <rc-guid>                  # by ResourceClaim provision GUID
./scripts/showroom-urls.sh -w <workshop-guid> -n <ns>    # limit to a namespace
```

Requires `oc` (logged in) and `jq`. Run `./scripts/showroom-urls.sh -h` for full usage.
