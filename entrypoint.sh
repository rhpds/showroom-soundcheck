#!/usr/bin/env bash
set -e

REFLEX_ENV="${REFLEX_ENV:-dev}"

echo "==> Initializing Reflex DB (alembic)..."

if ! reflex db init 2>&1; then
    echo "    (db already initialized, continuing)"
fi

if ! reflex db migrate 2>&1; then
    echo "ERROR: migration failed — database may be out of sync" >&2
    exit 1
fi

if [ "$REFLEX_ENV" = "dev" ]; then
    echo "==> Dev mode: generating migrations for any new model changes..."
    if reflex db makemigrations --message "auto" 2>&1; then
        echo "==> Applying newly generated migrations..."
        if ! reflex db migrate 2>&1; then
            echo "ERROR: migration failed after makemigrations" >&2
            exit 1
        fi
    else
        echo "    (no new changes detected)"
    fi
fi

echo "==> Starting Reflex app (env=$REFLEX_ENV)..."
exec reflex run --env "$REFLEX_ENV" --backend-host 0.0.0.0
