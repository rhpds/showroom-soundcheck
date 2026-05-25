##
# Showroom Soundcheck Dockerfile
#
# Multi-stage build:
#   1. Build SvelteKit frontend
#   2. Compile Python wheels
#   3. Runtime: install deps, copy frontend build, run FastAPI
##

# ---------------------------------------------------------------------------
# Stage 1: build SvelteKit frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY frontend/ .
RUN cp node_modules/@patternfly/patternfly/dist/patternfly.min.css static/patternfly.min.css
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: compile native Python wheels (gcc + pg headers)
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

USER 0
WORKDIR /build

RUN microdnf install -y --nodocs gcc python3-devel postgresql-devel \
    && microdnf clean all

COPY backend/requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3: runtime — FastAPI + static frontend
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

USER 0
WORKDIR /app

RUN microdnf install -y --nodocs \
    curl-minimal \
    postgresql-libs \
    && microdnf clean all

COPY --from=builder /wheels /wheels
COPY backend/requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY backend/ /app/
COPY --from=frontend /app/frontend/build /app/static

RUN chmod -R g=u /app /opt/app-root/src && \
    chown -R 1001:0 /app /opt/app-root/src

EXPOSE 8000

USER 1001

CMD ["bash", "/app/entrypoint.sh"]
