# OpenShift Deployment

Plain YAML manifests for deploying Showroom Soundcheck to OpenShift.

All traffic is gated by an OpenShift OAuth Proxy sidecar — users must
authenticate to the cluster before they can reach the Soundcheck UI.

## Architecture

```
Internet → Route (edge TLS)
            → Service :4180
              → oauth-proxy :4180  ← authenticates against OCP OAuth
                → frontend :5173   ← Node.js (SvelteKit static + /api proxy)
                    → backend :8000  ← FastAPI API server

backend ──┬──→ postgres :5432  (session/group/check data)
           └──→ redis :6379     (SAQ task queue + pub/sub events)

orchestration-worker ──→ redis + postgres  (fan-out session/group orchestration)
check-worker ──────────→ redis + postgres  (individual health checks)
```

## Prerequisites

- `oc` CLI logged into an OpenShift cluster
- Images pushed to:
  - `quay.io/rhpds/showroom-soundcheck-backend`
  - `quay.io/rhpds/showroom-soundcheck-frontend`

## Quick Start

```bash
# Create the namespace (or use oc new-project)
oc apply -f deploy/namespace.yaml

# Update secrets with real credentials (see below), then deploy
oc apply -f deploy/
```

## Configuration

### Secrets

Secret template files (`*-secret.yaml`) are git-ignored. Copy the templates,
fill in real values, and apply them to the cluster before deploying.

#### PostgreSQL credentials (`postgres-secret.yaml`)

Update `stringData` values before deploying:

| Key               | Description             |
|-------------------|-------------------------|
| POSTGRES_USER     | PostgreSQL username      |
| POSTGRES_PASSWORD | PostgreSQL password      |
| POSTGRES_DB       | PostgreSQL database name |

#### OAuth proxy session secret (`app-oauth-secret.yaml`)

| Key            | Description                                                    |
|----------------|----------------------------------------------------------------|
| session-secret | Random 32-byte string for cookie encryption (`openssl rand -base64 32 \| head -c 32`) |

### ConfigMap (`app-configmap.yaml`)

Shared by the backend and both workers:

| Key                       | Default | Description                                  |
|---------------------------|---------|----------------------------------------------|
| REDIS_URL                 | redis://redis:6379 | Redis connection URL (SAQ queue broker) |
| CHECK_CONCURRENCY         | 20      | Concurrent health checks per check-worker    |
| ORCHESTRATION_CONCURRENCY | 10      | Concurrent orchestration tasks per worker    |
| VERIFY_SSL                | false   | Verify SSL certificates during checks        |
| ALLOWED_URL_PATTERNS      |         | Comma-separated URL patterns to allow        |
| POSTGRES_HOST             | postgres| PostgreSQL service hostname                  |
| POSTGRES_PORT             | 5432    | PostgreSQL service port                      |
| BABYLON_CLUSTERS          | (JSON)  | JSON array of kubeconfig paths               |
| BABYLON_CATALOG_URLS      | (JSON)  | JSON map of cluster→catalog URL              |

### Updating Image Tags

After a new release, update the images across all deployments:

```bash
# Backend (API server + workers share the same image)
oc set image deployment/showroom-soundcheck-app \
  app=quay.io/rhpds/showroom-soundcheck-backend:v2.1.0 \
  -n showroom-soundcheck

oc set image deployment/showroom-soundcheck-orchestration-worker \
  worker=quay.io/rhpds/showroom-soundcheck-backend:v2.1.0 \
  -n showroom-soundcheck

oc set image deployment/showroom-soundcheck-check-worker \
  worker=quay.io/rhpds/showroom-soundcheck-backend:v2.1.0 \
  -n showroom-soundcheck

# Frontend
oc set image deployment/showroom-soundcheck-frontend \
  frontend=quay.io/rhpds/showroom-soundcheck-frontend:v2.1.0 \
  -n showroom-soundcheck
```

## Manifests

| File                        | Resource                                   |
|-----------------------------|--------------------------------------------|
| `namespace.yaml`            | Namespace                                  |
| `postgres-secret.yaml`      | Secret (DB credentials) — git-ignored      |
| `postgres-service.yaml`     | Headless Service (postgres)                |
| `postgres-statefulset.yaml` | StatefulSet (postgres)                     |
| `redis-deployment.yaml`     | Deployment (redis)                         |
| `redis-service.yaml`        | Service (redis)                            |
| `app-serviceaccount.yaml`   | ServiceAccount (OAuth redirect annotation) |
| `app-oauth-secret.yaml`     | Secret (proxy session cookie) — git-ignored |
| `app-configmap.yaml`        | ConfigMap (shared backend/worker settings) |
| `app-deployment.yaml`       | Deployment (FastAPI backend)               |
| `app-service.yaml`          | Service (backend HTTP)                     |
| `frontend-deployment.yaml`  | Deployment (SvelteKit frontend)            |
| `frontend-service.yaml`     | Service (frontend HTTP)                    |
| `worker-deployment.yaml`    | Deployments (orchestration + check workers)|
| `oauth-proxy-deployment.yaml` | Deployment (OAuth proxy)                 |
| `oauth-proxy-service.yaml`  | Service (proxy port 4180)                  |
| `app-route.yaml`            | Route (TLS edge → proxy)                   |
| `app-pdb.yaml`              | PodDisruptionBudget (backend availability) |
| `networkpolicy.yaml`        | NetworkPolicies (ingress restrictions)     |

## How the OAuth Proxy Works

```
Internet → Route (edge TLS)
            → Service :4180
              → oauth-proxy :4180  ← authenticates against OCP OAuth
                → frontend :5173   ← only reachable after auth
                    → backend :8000  ← /api requests proxied by frontend
```

1. The Route terminates external TLS at the edge and routes to the Service on port 4180.
2. The Service forwards to the `oauth-proxy` sidecar on port 4180.
3. The proxy validates the user's OCP session. Unauthenticated users are
   redirected to the OpenShift login page.
4. Authenticated requests are forwarded to the frontend on port 5173.
5. The frontend serves static assets directly and reverse-proxies `/api`
   requests to the backend on port 8000.

The serving certificate for the proxy is automatically provisioned by
OpenShift via the `service.beta.openshift.io/serving-cert-secret-name`
annotation on the Service.

## Workers

The app uses [SAQ](https://github.com/tobymao/saq) (Simple Async Queue) backed
by Redis for background task processing. Two worker deployments handle different
workloads:

**orchestration-worker** — Coordinates group runs and session fan-out. Low CPU,
needs access to Babylon kubeconfigs for metadata resolution.

**check-worker** — Executes individual HTTP health checks. Higher concurrency,
network-bound. Does not need kubeconfig access.

Both workers use the same backend container image — only the entrypoint
command differs.
