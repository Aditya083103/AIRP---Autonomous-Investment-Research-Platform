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
``enable_for_tests()`` at the start and ``reset_redis_client()`` in
teardown — no patching of os.environ required.

TTL constants (seconds) — match config.py cache_ttl_* fields:
    STOCK_TTL       =  21 600 ( 6 h)
    NEWS_TTL        =  43 200 (12 h)
    RATIOS_TTL      =  86 400 (24 h)
    MACRO_TTL       = 604 800 ( 7 d)
    FINANCIALS_TTL  =  43 200 (12 h)

Raised from the original dev values (15 min / 1 h / 1 h / 24 h) to protect
the free-tier API quotas (Alpha Vantage 25 req/day, NewsAPI 100 req/day)
under real public traffic on the deployed demo. Company fundamentals,
ratios, and macro data barely move intraday, so a long shared TTL is safe
and turns "ten users analyse TCS" into a single upstream call instead of
ten. The cache is keyed on ticker / company only (see the @cached templates
in backend/tools/*.py), so every user shares the same cached result.

Stale-on-error TTLs (T-087, Section A data-layer hardening)
-------------------------------------------------------------
In addition to the "fresh" TTLs above, ``backend.tools.cache.cached``
optionally writes a second, much longer-lived copy of every successful
fetch under a ``:stale`` key. When a live fetch fails even after
tenacity's retries are exhausted (persistent yFinance rate limiting, an
outage, etc.), the caller serves that stale copy (marked ``stale: True``)
instead of surfacing a blank error to the user — a stale price chart beats
no price chart. These TTLs are deliberately much longer than the fresh
TTLs above; they are the outer bound on "how out of date is acceptable
before we'd rather show nothing," not the normal refresh cadence.
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

STOCK_TTL: int = 21_600  # 6 hours (raised from 15 min for free-tier demo)
NEWS_TTL: int = 43_200  # 12 hours (raised from 1 h; NewsAPI 100 req/day)
RATIOS_TTL: int = 86_400  # 24 hours (raised from 1 h; Alpha Vantage 25 req/day)
MACRO_TTL: int = 604_800  # 7 days (raised from 24 h; macro data is slow-moving)
FINANCIALS_TTL: int = 43_200  # 12 hours (T-087: financials.py had NO caching
# before this fix -- every fetch_financials call hit yFinance live, even
# though annual statements change at most quarterly. This was the single
# biggest contributor to cold-run 429s alongside the redundant per-tool
# yf.Ticker() fan-out that backend.tools.market_data already fixed.

# Stale-on-error fallback TTLs (T-087) -- see module docstring above.
STOCK_STALE_TTL: int = 3 * 86_400  # 3 days
FINANCIALS_STALE_TTL: int = 7 * 86_400  # 7 days (annual data barely moves)
RATIOS_STALE_TTL: int = 7 * 86_400

# Connection timeouts — keep short so a dead Redis fails fast.
_SOCKET_TIMEOUT: int = 3
_SOCKET_CONNECT_TIMEOUT: int = 3

# ---------------------------------------------------------------------------
# Module-level memoised state
# ---------------------------------------------------------------------------

# redis.Redis is not generic at runtime in older redis-py versions;
# annotate as the plain class to satisfy mypy strict mode.
_client: redis.Redis | None = None
_client_unavailable: bool = False


def _is_test_environment() -> bool:
    """Return True when running under pytest (ENVIRONMENT=test)."""
    return os.getenv("ENVIRONMENT", "").strip().lower() == "test"


# When True, get_redis_client() always returns None regardless of env vars.
#
# Bound to _is_test_environment() rather than hardcoded True -- this used to
# be `_FORCE_DISABLE: bool = True`, "cleared only by enable_for_tests()",
# which meant every real uvicorn run (never calls enable_for_tests()) had
# caching permanently disabled, not just the test suite. That went
# unnoticed because every cache miss degrades silently to a live fetch (by
# design -- see this module's docstring), so nothing ever *looked* broken;
# it just meant fetch_stock_price/fetch_ratios/fetch_news/fetch_macro hit
# their live APIs on every single call, with no caching ever kicking in
# outside pytest. In practice this is most visible on fetch_ratios: with
# caching dead, both the Fundamental Analyst and the Valuation Agent's
# separate fetch_ratios calls for the same ticker each go live instead of
# the second one being a cache hit, doubling Alpha Vantage's free-tier
# 25-requests/day usage per analysis before even counting retries.
#
# Tests still get the exact same hermetic default: _is_test_environment()
# is True whenever ENVIRONMENT=test (which every test module in this repo
# sets before importing anything, per this project's documented "set
# ENVIRONMENT=test before pytest" rule) -- so this change alters behaviour
# for real (non-pytest) processes only.
_FORCE_DISABLE: bool = _is_test_environment()


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


def get_redis_client() -> redis.Redis | None:
    """
    Return a connected Redis client, or None if caching is unavailable.

    Returns None (caching disabled) when:
      * _FORCE_DISABLE is True (default under ENVIRONMENT=test; False in a
        real process -- see enable_for_tests()/_is_test_environment()).
      * _client_unavailable is True (latched after first connection failure).
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
        client: redis.Redis = redis.Redis.from_url(url, **kwargs)
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
    Has no effect on the actual Redis server -- it only drops the in-process
    handle and restores the default state (_FORCE_DISABLE=_is_test_environment(),
    i.e. True under pytest, False in a real process -- see _FORCE_DISABLE's
    module-level docstring for why this is no longer a hardcoded True).
    """
    global _client, _client_unavailable, _FORCE_DISABLE
    _client = None
    _client_unavailable = False
    _FORCE_DISABLE = _is_test_environment()
