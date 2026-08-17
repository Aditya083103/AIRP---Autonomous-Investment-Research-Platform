#!/usr/bin/env bash
# backend/docker-entrypoint.sh
# =============================================================================
# AIRP — Backend container entrypoint (T-073)
#
# Runs Alembic migrations against whatever DATABASE_URL is configured for
# this container BEFORE the application starts accepting traffic, then
# hands off to the CMD (uvicorn) via `exec "$@"`.
#
# Why this lives in the entrypoint and not in backend/main.py's lifespan:
# migrations must complete (or fail loudly) before uvicorn binds a port,
# not concurrently with request handling. Doing it here means both the
# production CMD and docker-compose's dev override (--reload) get
# migrations for free without duplicating the logic in two Dockerfile
# CMD lines.
#
# `alembic -c backend/alembic.ini` is run from /app (the image's
# WORKDIR = repo root), matching the exact invocation documented in
# backend/alembic.ini itself and in this project's CONTRIBUTING.md —
# so the same command works identically on a host machine and in this
# container.
#
# set -e: abort immediately (and fail the container) if the migration
# step fails, rather than starting an app pointed at a stale schema.
# =============================================================================
set -e

echo "[entrypoint] AIRP backend starting — environment=${ENVIRONMENT:-development}"
echo "[entrypoint] Running Alembic migrations (alembic -c backend/alembic.ini upgrade head)..."

alembic -c backend/alembic.ini upgrade head

echo "[entrypoint] Migrations complete. Starting application: $*"

exec "$@"
