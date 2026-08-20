# backend/Dockerfile
# =============================================================================
# AIRP — Backend (FastAPI) production image
# T-073: Dockerize the full stack
#
# IMPORTANT — build context is the REPO ROOT, not backend/:
#   docker build -f backend/Dockerfile .
#   (docker-compose.yml already sets `context: .` / `dockerfile: backend/Dockerfile`)
#
# Every backend module imports with the "backend." package prefix
# (e.g. `from backend.config import settings`, see backend/main.py and
# backend/alembic.ini's prepend_sys_path). That only resolves if the
# image's working directory is the repo root with a `backend/` package
# underneath it — building from ./backend as context (flattening the
# package into /app) would break every one of those imports at runtime.
#
# Two-stage build:
#   1. "builder" — installs build tools + compiles wheels into a venv.
#   2. final     — copies only the venv + app source; no compilers,
#      no pip cache, no apt lists left behind. Keeps the shipped image
#      free of the tool-chain used only to build it.
#
# NOTE ON BASE IMAGE PINNING (fix for exit code 100 apt failure):
# `python:3.11-slim` is a FLOATING tag — Docker Hub repoints it at
# whatever Debian release is currently "stable" (it moved from
# bookworm to trixie in 2025/2026). When that happens, apt package
# names inside the image can change or disappear out from under you
# with no warning (e.g. `libgdk-pixbuf2.0-0` was restructured in
# trixie). Pinning to `slim-bookworm` makes this build reproducible —
# apt-get install will keep working until we deliberately upgrade.
# =============================================================================

# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential   -> compiles any C-extension wheels without prebuilt
#                      manylinux wheels for this Python/arch combo
# libpq-dev         -> headers for asyncpg's optional C speedups
# libffi-dev        -> required to build cryptography (python-jose[cryptography])
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install into an isolated venv (not --user) so the whole environment
# copies cleanly into the final stage as one directory.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Only production deps — requirements-dev.txt (black/isort/flake8/mypy/
# pytest/...) is deliberately never installed in this image; those run
# in CI on the host runner, not inside the shipped container.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r backend/requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

# Runtime-only system libraries. WeasyPrint (backend/requirements.txt,
# used by the Portfolio Manager's Investment Memo PDF export, T-044)
# links against Pango/Cairo/GDK-Pixbuf at import time, NOT at build
# time — pip installing the weasyprint wheel succeeds without these,
# then the app crashes on first PDF render with
# "OSError: cannot load library 'libpango-1.0.so.0'". They must be
# present in the FINAL image, not just the builder stage.
#
# libgdk-pixbuf-2.0-0 (hyphen before "2.0") is the correct Debian
# bookworm/trixie package name — libgdk-pixbuf2.0-0 (no hyphen) was
# the old naming and no longer resolves on current Debian mirrors.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        shared-mime-info \
        fonts-liberation \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — never run the production process as root.
RUN groupadd --gid 1000 airp && \
    useradd --uid 1000 --gid airp --shell /bin/bash --create-home airp

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy only what the running application needs: the backend package
# itself. docs/, frontend/, scripts/, .git/, and the test suite are
# excluded via .dockerignore at the repo root — they add nothing to a
# running container and only bloat the image / cache-bust rebuilds.
COPY backend/ backend/

# CHROMA_PERSIST_DIR (backend/config.py) — the local-dev ChromaDB
# PersistentClient writes here. Created up front and owned by the
# non-root user so the app doesn't fail on first write with a
# permissions error; docker-compose.yml mounts a named volume over
# this path so embeddings survive container restarts.
RUN mkdir -p /app/.chroma_data data/memos && chown -R airp:airp /app

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER airp

EXPOSE 8000

# Liveness check against the T-045 /health endpoint (no downstream
# dependency checks by design — see backend/routers/health.py's own
# docstring for why). python -c avoids adding curl/wget as a runtime
# dependency just for this one check.
#
# T-074 audit finding C2: shell-form CMD (below) — HEALTHCHECK's CMD is
# already shell form (no JSON array), so $PORT expands here the same way
# it does in CMD; hardcoding 8000 in both would silently diverge from
# whatever port uvicorn actually bound once PORT is set (Render's
# convention — see CMD below).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '8000') + '/health', timeout=3)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]

# T-074 audit finding C2 (BLOCKER): shell form, not exec-form JSON array.
# Render (and most PaaS hosts) inject a $PORT env var and health-check
# THAT port, not a fixed one — exec-form CMD (a JSON array) never runs
# through a shell, so "--port", "8000" would be a hardcoded literal that
# never picks up $PORT and the service would never come up on Render.
# Shell form runs through /bin/sh -c, so ${PORT:-8000} expands at
# container start, keeping 8000 as the local/Docker Compose default (that
# file already sets PORT explicitly where it needs a specific one).
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}