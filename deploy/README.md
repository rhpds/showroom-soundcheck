# OpenShift Deployment

Plain YAML manifests for deploying Showroom Soundcheck to OpenShift.

All traffic is gated by an OpenShift OAuth Proxy sidecar — users must
authenticate to the cluster before they can reach the Soundcheck UI.

## Prerequisites

- `oc` CLI logged into an OpenShift cluster
- Images pushed to `quay.io/rhpds/showroom-soundcheck-app`

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

| Key               | Default | Description                       |
|-------------------|---------|-----------------------------------|
| CHECK_CONCURRENCY | 10      | Parallel health check concurrency |
| VERIFY_SSL        | false   | Verify SSL certificates           |
| REFLEX_ENV        | prod    | Reflex environment mode           |
| POSTGRES_HOST     | postgres| PostgreSQL service hostname       |
| POSTGRES_PORT     | 5432    | PostgreSQL service port           |
| BABYLON_CLUSTERS  | (JSON)  | JSON array of kubeconfig paths (order = search priority) |

### Updating the Image Tag

After a new release, update the image in the deployment:

```bash
oc set image deployment/showroom-soundcheck-app \
  app=quay.io/rhpds/showroom-soundcheck-app:v1.2.3 \
  -n showroom-soundcheck
```

## Manifests

| File                        | Resource                                   |
|-----------------------------|--------------------------------------------|
| `namespace.yaml`            | Namespace                                  |
| `postgres-secret.yaml`      | Secret (DB credentials) — git-ignored      |
| `postgres-service.yaml`     | Headless Service (postgres)                |
| `postgres-statefulset.yaml` | StatefulSet (postgres)                     |
| `app-serviceaccount.yaml`   | ServiceAccount (OAuth redirect annotation) |
| `app-oauth-secret.yaml`     | Secret (proxy session cookie) — git-ignored |
| `app-configmap.yaml`        | ConfigMap (app settings)                   |
| `app-deployment.yaml`       | Deployment (app + oauth-proxy sidecar)     |
| `app-service.yaml`          | Service (proxy + backend ports)            |
| `app-route.yaml`            | Route (TLS reencrypt → proxy)              |
| `app-pdb.yaml`              | PodDisruptionBudget (app availability)     |
| `networkpolicy.yaml`        | NetworkPolicies (ingress restrictions)     |

## How the OAuth Proxy Works

```
Internet → Route (reencrypt TLS)
            → Service :443
              → oauth-proxy :4180  ← authenticates against OCP OAuth
                → app :3000        ← only reachable after auth
```

1. The Route terminates external TLS and re-encrypts to the Service on port 443.
2. The Service forwards to the `oauth-proxy` sidecar on port 4180.
3. The proxy validates the user's OCP session. Unauthenticated users are
   redirected to the OpenShift login page.
4. Authenticated requests are forwarded to the Soundcheck app on `localhost:3000`.

The serving certificate for the proxy is automatically provisioned by
OpenShift via the `service.beta.openshift.io/serving-cert-secret-name`
annotation on the Service.
