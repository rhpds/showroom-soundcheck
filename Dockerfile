##
# Showroom Soundcheck Dockerfile
#
# Three-stage build following Reflex production best practices:
#   1. builder  — compile native wheels (gcc, pg headers)
#   2. init     — install deps, reflex init, export frontend
#   3. runtime  — slim image with pre-built frontend + backend
#
# OpenShift compatible: group-writable /app, runs as arbitrary UID
# in group 0 (standard OCP restricted SCC pattern).
##

# ---------------------------------------------------------------------------
# Stage 1: build native wheels
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

USER 0
WORKDIR /build

RUN microdnf install -y --nodocs gcc python3-devel postgresql-devel \
    && microdnf clean all

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: install deps, init reflex, export frontend
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS init

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

USER 0
WORKDIR /app

RUN microdnf install -y --nodocs \
    unzip \
    curl-minimal \
    postgresql-libs \
    && microdnf clean all

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY . /app

RUN reflex init
RUN reflex export --frontend-only --no-zip

# Strip .web down to just the built static frontend
RUN mv .web/build/client /tmp/client \
    && rm -rf .web && mkdir -p .web/build \
    && mv /tmp/client .web/build/client

# ---------------------------------------------------------------------------
# Stage 3: slim runtime image
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    REFLEX_ENV=prod

USER 0
WORKDIR /app

RUN microdnf install -y --nodocs \
    curl-minimal \
    postgresql-libs \
    && microdnf clean all

COPY --from=init /opt/app-root/lib64/python3.12/site-packages /opt/app-root/lib64/python3.12/site-packages
COPY --from=init /opt/app-root/bin /opt/app-root/bin
COPY --from=init /app /app

# Patch copytree to use shutil.copy (no metadata preservation) so it works
# under OpenShift's restricted SCC which drops CAP_FOWNER.
RUN sed -i 's/dirs_exist_ok=True,/dirs_exist_ok=True, copy_function=shutil.copy,/' \
      /opt/app-root/lib64/python3.12/site-packages/reflex/utils/path_ops.py \
    && chmod -R g=u /app

EXPOSE 3000 8000

USER 1001

CMD ["bash", "/app/entrypoint.sh"]
