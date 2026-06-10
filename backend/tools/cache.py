# backend/tools/cache.py
"""
AIRP — Redis JSON cache helper + @cached decorator (T-018).

This module provides two public surfaces:

1. Low-level helpers (backward-compatible with T-014):
       cache_get_json(key)            -> dict | None
       cache_set_json(key, value, ttl) -> bool
       get_client()                   -> redis.Redis | None
       reset_client()                 -> None

2. @cached decorator — wraps any ``_fetch_*()`` inner function so the
   result is transparently read from Redis on a cache hit and written on a
   miss.  All tool caches share the same Redis connection from
   ``backend.db.redis_client``.

   Usage:
       @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
       def _fetch_stock(ticker: str, period: str) -> dict[str, Any]:
           ...

   Key templating:
       Curly-brace placeholders are resolved against the function's keyword
       arguments (after Python binds positional args).  For example the key
       template ``"airp:news:{company_name}"`` with a call
       ``_fetch_news(company_name="TCS")`` resolves to ``"airp:news:TCS"``.

Design rules:
    * Never raise.  A cache is an optimisation, never a hard dependency.
    * Bypass entirely when ENVIRONMENT=test so unit tests are hermetic.
    * Degrade silently — if Redis is unreachable the wrapped function is
      called as if the decorator were not there.
    * ``default=str`` in json.dumps lets datetime / Decimal / etc. serialise
      without a custom encoder.
    * A non-dict cached value is treated as a miss (safe against schema
      evolution where a list was cached before a refactor made it a dict).

TTL constants are imported from ``backend.db.redis_client`` and re-exported
here for convenience.  Callers that only need one TTL can do:
    from backend.tools.cache import STOCK_TTL
"""

import functools
import inspect
import json
import logging
from typing import Any, Callable

import redis

try:
    from backend.config import settings as _settings
except Exception:  # config import is best-effort; env vars are the fallback
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.cache.settings") replaces this object
settings = _settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL re-exports (single source of truth lives in redis_client)
# ---------------------------------------------------------------------------

try:
    from backend.db.redis_client import (
        MACRO_TTL,
        NEWS_TTL,
        RATIOS_TTL,
        STOCK_TTL,
        get_redis_client,
        reset_redis_client,
    )

    def reset_client() -> None:
        """Reset the memoised Redis client (delegates to redis_client module)."""
        reset_redis_client()

    def get_client() -> redis.Redis | None:
        """Return the shared Redis client (delegates to redis_client module)."""
        return get_redis_client()

except ImportError:
    # Fallback if redis_client is not yet importable (should not happen in
    # normal usage, but prevents a hard crash during partial installs).
    STOCK_TTL = 900
    NEWS_TTL = 3_600
    RATIOS_TTL = 3_600
    MACRO_TTL = 86_400

    def get_client() -> redis.Redis | None:  # type: ignore[misc]
        """Fallback get_client when redis_client module is unavailable."""
        return None

    def reset_client() -> None:  # type: ignore[misc]
        """Fallback reset_client when redis_client module is unavailable."""
        pass


# ---------------------------------------------------------------------------
# Public API — explicit exports so mypy strict mode is satisfied
# ---------------------------------------------------------------------------

__all__ = [
    "STOCK_TTL",
    "NEWS_TTL",
    "RATIOS_TTL",
    "MACRO_TTL",
    "get_client",
    "reset_client",
    "cache_get_json",
    "cache_set_json",
    "cached",
]


# ---------------------------------------------------------------------------
# Low-level JSON helpers
# ---------------------------------------------------------------------------


def cache_get_json(key: str) -> dict[str, Any] | None:
    """
    Return the cached JSON object for ``key``, or None on miss / unavailable.

    Never raises.  A corrupt or non-dict cached value is treated as a miss
    and logged, so a poisoned key can never crash the caller.
    """
    client = get_client()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:
        logger.warning("Redis GET failed for %r — treating as miss: %s", key, exc)
        return None

    if not raw:
        return None

    # client has decode_responses=True so raw is always str, not bytes.
    # Cast to str to satisfy mypy — redis-py stubs type .get() as
    # Awaitable[Any] | Any in some versions.
    raw_str: str = str(raw)

    try:
        data = json.loads(raw_str)
    except (TypeError, ValueError) as exc:
        logger.warning("Corrupt cache value for %r — treating as miss: %s", key, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("Cached value for %r is not a JSON object — ignoring", key)
        return None

    return data  # type: ignore[return-value]


def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> bool:
    """
    Store ``value`` as JSON under ``key`` with a TTL.  Returns True on success.

    Never raises — a failed write returns False and the caller carries on
    with the freshly fetched value.  ``default=str`` lets datetime and other
    non-JSON-native types serialise without a custom encoder.
    """
    client = get_client()
    if client is None:
        return False

    try:
        payload = json.dumps(value, default=str)
        client.set(key, payload, ex=max(1, ttl_seconds))
        return True
    except Exception as exc:
        logger.warning("Redis SET failed for %r — value not cached: %s", key, exc)
        return False


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------

_FuncT = Callable[..., dict[str, Any]]


def cached(*, key: str, ttl: int) -> Callable[[_FuncT], _FuncT]:
    """
    Decorator that wraps a data-fetch function with a Redis read-through cache.

    Parameters
    ----------
    key:
        Redis key template.  Curly-brace placeholders (e.g. ``{ticker}``)
        are resolved against the function's bound arguments at call time.
    ttl:
        Time-to-live in seconds.  Use the TTL constants from this module
        (STOCK_TTL, NEWS_TTL, RATIOS_TTL, MACRO_TTL).

    Behaviour
    ---------
    * Cache hit  → return the cached dict immediately (no network call).
    * Cache miss → call the wrapped function, cache the result, return it.
    * Redis unavailable → call the wrapped function normally (no caching).
    * A result containing an ``"error"`` key is NOT cached.

    Example
    -------
        @cached(key="airp:stock:{ticker}:{period}", ttl=STOCK_TTL)
        def _fetch_stock_data(ticker: str, period: str) -> dict[str, Any]:
            ...  # yFinance call
    """

    def decorator(func: _FuncT) -> _FuncT:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                resolved_key = key.format_map(bound.arguments)
            except (KeyError, IndexError) as exc:
                logger.warning(
                    "Could not resolve cache key template %r: %s — "
                    "bypassing cache for this call",
                    key,
                    exc,
                )
                return func(*args, **kwargs)

            cached_value = cache_get_json(resolved_key)
            if cached_value is not None:
                logger.debug("Cache hit: %s", resolved_key)
                return cached_value

            logger.debug("Cache miss: %s", resolved_key)

            result: dict[str, Any] = func(*args, **kwargs)

            if "error" not in result:
                cache_set_json(resolved_key, result, ttl)

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
