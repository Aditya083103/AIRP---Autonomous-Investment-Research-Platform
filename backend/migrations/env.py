# backend/migrations/env.py
"""
Alembic migration environment — AIRP.

Configured for:
  * Async SQLAlchemy engine (asyncpg driver)
  * Automatic metadata import from backend.models so ``alembic revision
    --autogenerate`` detects schema changes without manual column lists
  * ``active_database_url`` from settings so the correct DB is used in
    every environment (dev → Neon; test → airp_test; CI → airp_test)

Usage:
    alembic upgrade head          # apply all pending migrations
    alembic downgrade -1          # roll back one migration
    alembic revision --autogenerate -m "add foo column"
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from pathlib import Path
import re
import sys
from typing import Any

# ── Ensure repo root is on sys.path ─────────────────────────────────────────
# env.py lives at backend/migrations/env.py.
# parents[0] = backend/migrations/
# parents[1] = backend/
# parents[2] = repo root  ← must be on sys.path for "from backend.X import"
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from alembic import context  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy.engine import Connection  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from backend.config import settings  # noqa: E402

# ── Import AIRP models so their metadata is visible to autogenerate ──────────
from backend.models import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic config object — gives access to the .ini file values
# ---------------------------------------------------------------------------

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# URL + SSL helpers
# ---------------------------------------------------------------------------


def _strip_ssl_params(url: str) -> str:
    """
    Remove all SSL-related query parameters from a database URL.

    asyncpg requires SSL to be configured via ``connect_args``, not via
    query string parameters.  Both ``sslmode=`` and ``ssl=`` must be
    stripped so asyncpg never sees them in the DSN.

    Examples:
        ?sslmode=require            → (empty)
        ?sslmode=require&other=1    → ?other=1
        ?other=1&sslmode=require    → ?other=1
    """
    # Remove sslmode and ssl query params (handles both ? and & delimiters)
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]ssl=[^&]*", "", url)
    # If removal left a dangling & at the start of the query string, fix it
    url = re.sub(r"\?&", "?", url)
    return url


def _needs_ssl(raw_url: str) -> bool:
    """Return True when the original URL contained an SSL requirement."""
    return "sslmode=require" in raw_url or "ssl=require" in raw_url


def _get_engine_args() -> tuple[str, dict[str, Any]]:
    """
    Return (clean_url, connect_args) for create_async_engine.

    Neon cloud URLs arrive as:
        postgresql+asyncpg://user:pass@host/db?sslmode=require

    asyncpg does NOT accept ``sslmode`` or ``ssl=true`` as query params —
    it only accepts them via the ``ssl`` keyword in connect_args.
    The correct value is the Python boolean ``True``, which tells asyncpg
    to establish a TLS connection and verify the server certificate using
    the OS trust store (same behaviour as ``sslmode=require``).
    """
    raw = settings.active_database_url
    clean_url = _strip_ssl_params(raw)
    connect_args: dict[str, Any] = {}
    if _needs_ssl(raw):
        connect_args["ssl"] = True
    return clean_url, connect_args


# ---------------------------------------------------------------------------
# Offline mode — generates SQL without connecting to the DB
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (generates SQL, no DB connection).

    Usage:
        alembic upgrade head --sql
    """
    url, _ = _get_engine_args()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connects and applies migrations
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Apply migrations using an existing synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations inside a sync runner.

    Alembic's internal machinery is synchronous; ``run_sync`` bridges the
    gap by running ``do_run_migrations`` in a thread-safe synchronous
    context while keeping the asyncpg connection alive.
    """
    url, connect_args = _get_engine_args()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online mode — called by Alembic CLI."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
