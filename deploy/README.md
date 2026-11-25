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

#### App secrets (`app-secret.yaml`)

| Key              | Description                                                                     |
|------------------|----------------------------------------------------------------------------------|
| DEMO_TEAM_EMAILS | Comma-separated emails treated as "Demo team" provisioners for the workshop dashboard's "Provisioned by" filter |

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
| BABYLON_DEFAULT_CLUSTERS  | (JSON, empty → all configured) | JSON array of clusters pre-selected on the workshop dashboard's cluster filter |
| CORS_ORIGINS              | (empty → localhost default in app) | Comma-separated browser origins allowed to call the API (no `*`) |

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
| `redis-deployment.yaml`     | PersistentVolumeClaim + Deployment (redis) |
| `redis-service.yaml`        | Service (redis)                            |
| `app-serviceaccount.yaml`   | ServiceAccount (OAuth redirect annotation) |
| `app-oauth-secret.yaml`     | Secret (proxy session cookie) — git-ignored |
| `app-secret.yaml`           | Secret (demo team email roster) — git-ignored |
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

### API access with a Bearer token

Browser users log in as above. API clients such as RHDP Flow QA can't follow
the login redirect, so the proxy also accepts a Bearer token on `/api/`
(`-openshift-delegate-urls`). It validates the token with a TokenReview, then
checks that the caller can `get` services in this namespace.

The proxy's service account needs permission to run those reviews. A cluster
admin grants it once per namespace:

```bash
oc adm policy add-cluster-role-to-user system:auth-delegator \
  -z showroom-soundcheck-proxy -n showroom-soundcheck-dev
```

To issue a token for a client, create a service account it can use and give it
read access to services in the namespace:

```bash
NS=showroom-soundcheck-dev
oc create serviceaccount soundcheck-api-client -n "$NS"
oc create role soundcheck-api-client --verb=get --resource=services -n "$NS"
oc create rolebinding soundcheck-api-client --role=soundcheck-api-client \
  --serviceaccount="$NS:soundcheck-api-client" -n "$NS"
oc create token soundcheck-api-client -n "$NS" --duration=8760h
```

The client sends it as `Authorization: Bearer <token>`. For Flow, that's the
`SOUNDCHECK_TOKEN` secret value. A request without a valid token still gets the
login redirect, so `/api` is never open to anonymous callers.

Check it from outside the cluster:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" \
  https://showroom-soundcheck-dev.apps.ocpv-infra01.dal12.infra.demo.redhat.com/api/ping
```

`200` means the token got through. `302` means the token is missing or invalid,
or the auth-delegator grant above hasn't been made. `403` means the token is
valid but can't `get` services in the namespace.

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
