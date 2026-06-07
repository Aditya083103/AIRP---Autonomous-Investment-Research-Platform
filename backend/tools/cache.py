# backend/tools/cache.py
"""
AIRP — Minimal Redis JSON cache helper.

This is a deliberately small, dependency-light cache helper introduced in
T-014 to satisfy the "cached in Redis for 24h" acceptance criterion of the
fetch_macro_data tool. It provides JSON get/set with a TTL and **degrades
gracefully**: if Redis is unreachable, not configured, or the process is
running under pytest (ENVIRONMENT=test), every call becomes a silent no-op
and the caller simply hits the live data source instead.

Relationship to T-018:
    T-018 ("Setup Redis caching layer") will generalise this into the
    documented ``@cached`` decorator for *all* data tools and move the Redis
    client into ``backend/db/redis_client.py``. At that point macro.py (and
    the other tools) switch to the decorator with no behavioural change —
    this module is the seed of that work, not a parallel implementation.

Design rules:
    * Never raise. A cache is an optimisation, never a hard dependency.
    * Bypass entirely when ENVIRONMENT=test so unit tests are hermetic and
      never touch a real Redis server.
    * Lazy, memoised connection — connect on first use, reuse afterwards,
      and remember a failed connection so we do not retry on every call.

Usage:
    from backend.tools.cache import cache_get_json, cache_set_json

    cached = cache_get_json("airp:macro:india")
    if cached is not None:
        return cached
    fresh = expensive_fetch()
    cache_set_json("airp:macro:india", fresh, ttl_seconds=86400)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis

try:
    from backend.config import settings as _settings
except Exception:  # config import is best-effort; env vars are the fallback
    _settings = None  # type: ignore[assignment]

# Module-level alias — patch target in tests:
#   patch("backend.tools.cache.settings") replaces this object
settings = _settings

logger = logging.getLogger(__name__)

# Memoised connection state. _client is the live client once connected;
# _client_unavailable latches True after a failed connect so we stop retrying.
_client: redis.Redis | None = None
_client_unavailable: bool = False

# Connection timeouts (seconds) — keep short so a dead Redis fails fast and
# the caller falls back to the live source without a noticeable stall.
_SOCKET_TIMEOUT = 3
_SOCKET_CONNECT_TIMEOUT = 3


def _is_test_environment() -> bool:
    """Return True when running under pytest (ENVIRONMENT=test)."""
    # strip().lower() so a trailing space / casing (Windows `set VAR=test `)
    # still routes caching to a no-op during tests.
    return os.getenv("ENVIRONMENT", "").strip().lower() == "test"


def _resolve_redis_url() -> str:
    """Resolve the Redis URL from the environment first, then settings."""
    url = os.getenv("REDIS_URL", "")
    if not url and settings is not None:
        url = settings.redis_url or ""
    return url


def _resolve_redis_token() -> str:
    """Resolve the Upstash token (used as password) if one is configured."""
    token = os.getenv("REDIS_TOKEN", "")
    if not token and settings is not None:
        token = settings.redis_token or ""
    return token


def get_client() -> redis.Redis | None:
    """
    Return a connected Redis client, or None if caching is unavailable.

    Returns None (caching disabled) when:
      * ENVIRONMENT=test — tests must never touch a real Redis server,
      * no REDIS_URL is configured,
      * the server is unreachable (connection verified with PING).

    The client and any "unavailable" verdict are memoised at module level,
    so the connection cost and the PING check happen at most once per process.
    """
    global _client, _client_unavailable

    if _is_test_environment() or _client_unavailable:
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
        client = redis.Redis.from_url(url, **kwargs)
        client.ping()  # verify connectivity now so later GET/SET cannot stall
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — caching disabled this run", exc)
        _client_unavailable = True
        return None

    _client = client
    logger.info("Redis cache connected")
    return _client


def cache_get_json(key: str) -> dict[str, Any] | None:
    """
    Return the cached JSON object for ``key``, or None on miss / unavailable.

    Never raises. A corrupt or non-dict cached value is treated as a miss
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

    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Corrupt cache value for %r — treating as miss: %s", key, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("Cached value for %r is not a JSON object — ignoring", key)
        return None
    return data


def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> bool:
    """
    Store ``value`` as JSON under ``key`` with a TTL. Returns True on success.

    Never raises — a failed write simply returns False and the caller carries
    on with the freshly fetched value. ``default=str`` lets datetime and other
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


def reset_client() -> None:
    """
    Reset the memoised client and availability flag.

    Used by tests to clear state between cases. Has no effect on a live Redis
    server — it only drops the in-process handle so the next get_client()
    reconnects from scratch.
    """
    global _client, _client_unavailable
    _client = None
    _client_unavailable = False
