# backend/db/session.py
"""
AIRP — Async SQLAlchemy Engine & Session Factory (T-016)

Provides the single async engine and session factory used by the entire
backend.  FastAPI route handlers receive an ``AsyncSession`` via the
``get_async_session`` dependency; background tasks (LangGraph agents) call
``get_async_session`` as an async context manager.

Design:
    * ``create_async_engine`` with NullPool when ENVIRONMENT=test so each
      test connection is closed immediately — asyncpg does not mix well with
      pytest's event loop teardown when a pool is left open.
    * ``pool_pre_ping=True`` on every pooled (non-test) engine — Neon's
      serverless Postgres can silently close idle connections server-side
      (autosuspend / connection recycling) without the client driver
      noticing until the connection is next used. Without pre-ping, a
      stale pooled connection surfaces as
      ``asyncpg.exceptions._base.InterfaceError: connection is closed``
      the moment a request tries to use it — pre-ping issues a cheap
      liveness check (``SELECT 1``) before handing a connection out and
      transparently reconnects if it's dead, so callers never see this.
    * ``expire_on_commit=False`` on the session factory so ORM objects
      remain accessible after ``session.commit()`` without a re-query.
    * SSL for Neon cloud is passed via ``connect_args={"ssl": True}`` —
      asyncpg does not accept sslmode/ssl as URL query parameters.
    * The engine is a module-level singleton — created once on first import
      and reused across all requests in the same process.

Usage (FastAPI dependency):
    from backend.db.session import get_async_session
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/analyses")
    async def list_analyses(
        session: AsyncSession = Depends(get_async_session),
    ) -> list[dict]:
        ...

Usage (background task / agent):
    from backend.db.session import get_async_session

    async with get_async_session() as session:
        session.add(analysis)
        await session.commit()
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import os
import re
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

try:
    from backend.config import settings as _settings
except Exception:
    _settings = None  # type: ignore[assignment]

settings = _settings

# ---------------------------------------------------------------------------
# SSL helpers
# ---------------------------------------------------------------------------

_IS_TEST = os.getenv("ENVIRONMENT", "").strip().lower() == "test"


def _strip_ssl_params(url: str) -> str:
    """
    Remove sslmode/ssl query params from a database URL.

    asyncpg requires SSL via connect_args, not URL query strings.
    Strips both ``?sslmode=require`` and ``?ssl=...`` variants so asyncpg
    never sees them in the DSN.
    """
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]ssl=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url)
    return url


def _needs_ssl(url: str) -> bool:
    """Return True when the original URL signals SSL is required."""
    return "sslmode=require" in url or "ssl=require" in url


def _prepare_url(raw_url: str) -> tuple[str, dict[str, Any]]:
    """
    Return (clean_url, connect_args) ready for create_async_engine.

    Neon cloud URLs use ``?sslmode=require`` (psycopg2 convention).
    asyncpg accepts SSL only as a Python bool in connect_args["ssl"].
    This function strips the param from the URL and moves it to
    connect_args so the connection is established correctly on both
    local (no SSL) and Neon cloud (SSL required) databases.
    """
    needs = _needs_ssl(raw_url)
    clean = _strip_ssl_params(raw_url)
    connect_args: dict[str, Any] = {"ssl": True} if needs else {}
    return clean, connect_args


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------


def _build_database_url() -> str:
    """
    Return the raw async PostgreSQL URL for the current environment.

    Prefers the module-level ``settings`` object; falls back to the
    DATABASE_URL environment variable so the session module works even
    when config.py cannot be imported.
    """
    if settings is not None:
        return settings.active_database_url
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://airp:airp@localhost:5432/airp",
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _build_engine() -> AsyncEngine:
    """
    Create the SQLAlchemy async engine with appropriate pool settings.

    NullPool is used in test environments so asyncpg connections are
    closed immediately after each test — prevents event-loop teardown
    errors when pytest exits. NullPool opens a brand-new connection on
    every checkout, so there is never a stale pooled connection to
    pre-ping there; ``pool_pre_ping`` is therefore only added on the two
    branches below that actually retain a pool across requests (dev and
    production), where a connection can otherwise sit idle long enough
    for Neon to close it server-side before the next request reuses it.
    """
    raw_url = _build_database_url()
    url, connect_args = _prepare_url(raw_url)

    if _IS_TEST:
        return create_async_engine(
            url,
            echo=False,
            poolclass=NullPool,
            connect_args=connect_args,
        )
    if settings is not None:
        return create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            connect_args=connect_args,
        )
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


# Module-level singleton engine — created once per process.
engine = _build_engine()

# Session factory — all sessions share the same engine.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Dependency / context manager
# ---------------------------------------------------------------------------


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an ``AsyncSession`` and close it on exit.

    Works both as a FastAPI ``Depends`` dependency and as an async
    context manager via ``async with get_async_session() as session``.

    The session is rolled back automatically on exception so callers do
    not need to call ``session.rollback()`` explicitly.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
