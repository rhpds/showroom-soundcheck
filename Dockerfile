##
# Showroom Soundcheck Dockerfile
#
# Multi-stage build: compile wheels in builder, install in slim runtime.
# Defaults to production mode (REFLEX_ENV=prod). Override via env var or
# docker-compose for development (REFLEX_ENV=dev + bind mount).
#
# Designed for rootless Podman: root inside the container maps to
# your unprivileged host UID, so no user-switching is needed.
##

FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

USER 0
WORKDIR /app

RUN microdnf install -y --nodocs gcc python3-devel postgresql-devel \
    && microdnf clean all

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip wheel --wheel-dir /wheels -r /app/requirements.txt


FROM registry.access.redhat.com/ubi10/python-312-minimal:latest AS runtime

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
COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-index --find-links=/wheels -r /app/requirements.txt \
    && rm -rf /wheels

COPY . /app

ENV REFLEX_ENV=prod

EXPOSE 3000 8000

CMD ["bash", "/app/entrypoint.sh"]
