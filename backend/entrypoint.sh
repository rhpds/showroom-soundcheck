#!/usr/bin/env bash
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "==> Running database migrations..."
    cd /app
    alembic upgrade head
else
    echo "==> Skipping migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS})"
fi

echo "==> Starting Soundcheck API..."
exec uvicorn soundcheck.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    ${UVICORN_WORKERS:+--workers $UVICORN_WORKERS} \
    ${UVICORN_RELOAD:+--reload}
