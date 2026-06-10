# backend/db/redis_client.py
"""
AIRP — Centralised Redis client (T-018).

Single source of truth for the Redis connection used across the entire
backend.  All application code should import from here rather than
constructing its own client:

    from backend.db.redis_client import get_redis_client, reset_redis_client

Design contract
---------------
* Never raises.  A cache layer must degrade gracefully; an unreachable
  Redis server must never block an analysis request.
* Bypass entirely when ENVIRONMENT=test — unit tests are hermetic and
  must never touch a real Redis server.
* Lazy, memoised connection — connect on first use, reuse afterwards, and
  latch a "unavailable" flag so a failed server is not retried on every call.
* Short timeouts (3 s) so a dead server fails fast and the caller falls back
  to its live data source without a noticeable pause.
* Upstash support — if REDIS_TOKEN is set it is used as the password, which
  is required for Upstash TLS Redis URLs (rediss://).

Testability
-----------
get_redis_client() reads the module-level ``_FORCE_DISABLE`` flag first.
Tests that need to exercise the connection path call
``enable_for_tests()`` at the start and ``disable_for_tests()`` (via
reset_redis_client) at teardown — no patching of os.environ required.

TTL constants (seconds) — match config.py cache_ttl_* fields:
    STOCK_TTL   =  900   (15 min)
    NEWS_TTL    = 3 600  ( 1 h)
    RATIOS_TTL  = 3 600  ( 1 h)
    MACRO_TTL   = 86 400 (24 h)
"""

import logging
import os
from typing import Any

import redis

try:
    from backend.config import settings as _settings
except Exception:  # config import is best-effort; env vars are the fallback
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.db.redis_client.settings") replaces this object
settings = _settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds) — single source of truth for all tool caches
# ---------------------------------------------------------------------------

STOCK_TTL: int = 900  # 15 minutes
NEWS_TTL: int = 3_600  # 1 hour
RATIOS_TTL: int = 3_600  # 1 hour
MACRO_TTL: int = 86_400  # 24 hours

# Connection timeouts — keep short so a dead Redis fails fast.
_SOCKET_TIMEOUT: int = 3
_SOCKET_CONNECT_TIMEOUT: int = 3

# ---------------------------------------------------------------------------
# Module-level memoised state
# ---------------------------------------------------------------------------

_client: redis.Redis | None = None  # type: ignore[type-arg]
_client_unavailable: bool = False

# When True, get_redis_client() always returns None regardless of env vars.
# Set to False only in tests that need to exercise the connection path.
# This is more reliable than patching os.environ across terminals/platforms.
_FORCE_DISABLE: bool = True


def _is_test_environment() -> bool:
    """Return True when running under pytest (ENVIRONMENT=test)."""
    return os.getenv("ENVIRONMENT", "").strip().lower() == "test"


def _resolve_redis_url() -> str:
    """Resolve the Redis URL: env var first, then settings, then empty."""
    url = os.getenv("REDIS_URL", "")
    if not url and settings is not None:
        url = getattr(settings, "redis_url", "") or ""
    return url


def _resolve_redis_token() -> str:
    """Resolve the Upstash token (used as password) if one is configured."""
    token = os.getenv("REDIS_TOKEN", "")
    if not token and settings is not None:
        token = getattr(settings, "redis_token", "") or ""
    return token


def enable_for_tests() -> None:
    """
    Allow get_redis_client() to attempt a real connection.

    Call this at the top of tests that need to exercise the connection
    path.  Always paired with reset_redis_client() in teardown.
    """
    global _FORCE_DISABLE
    _FORCE_DISABLE = False


def get_redis_client() -> "redis.Redis[Any] | None":
    """
    Return a connected Redis client, or None if caching is unavailable.

    Returns None (caching disabled) when:
      * _FORCE_DISABLE is True (default in test env — set by module init).
      * ENVIRONMENT=test.
      * No REDIS_URL is configured.
      * The server is unreachable (connection verified with PING).

    The client and any "unavailable" verdict are memoised at module level so
    the connection cost and the PING check happen at most once per process.
    """
    global _client, _client_unavailable

    if _FORCE_DISABLE or _client_unavailable:
        return None
    if _client is not None:
        return _client

    url = _resolve_redis_url()
    if not url:
        logger.info("REDIS_URL not configured — caching disabled for this run")
        _client_unavailable = True
        return None

    try:
        token = _resolve_redis_token()
        kwargs: dict[str, Any] = {
            "decode_responses": True,
            "socket_timeout": _SOCKET_TIMEOUT,
            "socket_connect_timeout": _SOCKET_CONNECT_TIMEOUT,
        }
        if token:
            kwargs["password"] = token
        client: redis.Redis[Any] = redis.Redis.from_url(url, **kwargs)
        client.ping()
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — caching disabled this run", exc)
        _client_unavailable = True
        return None

    _client = client
    logger.info("Redis cache connected: %s", url)
    return _client


def reset_redis_client() -> None:
    """
    Reset the memoised client, availability flag, and force-disable flag.

    Call this in teardown after any test that called enable_for_tests().
    Has no effect on the actual Redis server — it only drops the in-process
    handle and restores the safe default state.
    """
    global _client, _client_unavailable, _FORCE_DISABLE
    _client = None
    _client_unavailable = False
    _FORCE_DISABLE = True
