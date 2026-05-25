##
# Showroom Soundcheck Backend
#
# Multi-stage build:
#   1. Compile native Python wheels (gcc + pg headers)
#   2. Runtime: install deps, run FastAPI / SAQ workers
##

# ---------------------------------------------------------------------------
# Stage 1: compile native Python wheels
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
# Stage 2: runtime — FastAPI API server + SAQ workers
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
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY . /app/

RUN chmod -R g=u /app /opt/app-root/src && \
    chown -R 1001:0 /app /opt/app-root/src

EXPOSE 8000

USER 1001

CMD ["bash", "/app/entrypoint.sh"]
