##
# Showroom Soundcheck Dockerfile
#
# Two-stage build: compile native wheels in builder, then install
# deps, init Reflex, and export the frontend in the runtime image.
#
# Follows the official Reflex simple-two-port deployment pattern:
# reflex init + export at build time, reflex run --env prod at runtime.
##

# ---------------------------------------------------------------------------
# Stage 1: compile native wheels (gcc + pg headers)
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
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
# Stage 2: runtime — install deps, build frontend, run app
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

# Build frontend at image build time (no npm/bun work at runtime)
RUN reflex init
RUN reflex export --frontend-only --no-zip

RUN chmod -R g=u /app /opt/app-root/src && \
    chown -R 1001:0 /app /opt/app-root/src

STOPSIGNAL SIGKILL

EXPOSE 3000 8000

USER 1001

CMD ["bash", "/app/entrypoint.sh"]
