# backend/tools/market_data.py
"""
AIRP — Shared yFinance ticker fetch layer (backend hardening, post-Phase 6)

Problem this module fixes
--------------------------
Before this module existed, three independent tools each constructed their
own ``yf.Ticker(ticker)`` instance and pulled overlapping data:

    stock_price.py — .history() + .info                      (~2 calls)
    financials.py  — .financials + .balance_sheet + .cashflow
                     + .info                                   (~4 calls)
    ratios.py      — its own yf.Ticker() + .info + statements  (~several)

A single analysis therefore triggered 8-12 separate yfinance requests in
one burst for a single ticker. Yahoo Finance has no official published
rate limit (yfinance is unofficial scraping), but it is burst-sensitive —
this redundant fan-out was the most likely reason analyses got rate
limited (HTTP 429) on the very first ("cold") run of a ticker, before
Redis caching (``backend.tools.cache``, T-018) could help at all — Redis
only protects *repeat* runs of the same ticker, never the first one.

Fix
---
``get_shared_ticker(ticker)`` hands out one ``yf.Ticker`` instance per
ticker, shared across ``stock_price.py``, ``financials.py``, and
``ratios.py`` for the lifetime of a single analysis run. This matters
because yfinance's ``Ticker`` object caches ``.info``, ``.financials``,
``.balance_sheet``, ``.cashflow``, and ``.history()`` *on the instance*
after first access — accessing `.financials`/`.balance_sheet`/`.cashflow`
on a fresh ``yf.Ticker`` even triggers one shared network fetch that
populates all three internally. None of that caching helps when each
tool builds its own instance; it collapses the redundant fan-out down to
one instance ⇒ one round of underlying HTTP calls once all three tools
have touched the ticker, instead of three duplicate rounds.

This is deliberately an *in-process, short-lived* cache, not a
replacement for Redis:

    * Redis (``backend.tools.cache``) remains the source of truth for
      cross-analysis caching, with its existing, unchanged TTLs and key
      structure (STOCK_TTL, RATIOS_TTL, ...). A Redis cache hit still
      means zero yfinance calls, exactly as before.
    * The shared ``yf.Ticker`` instance here only needs to survive one
      analysis pipeline run (documented elsewhere in this project as
      completing in well under 90 seconds), so ``_SHARED_TICKER_TTL_SECONDS``
      is set generously above that and nothing more. Instances are never
      kept indefinitely — that would silently serve stale data to a
      *later*, separate analysis of the same ticker, quietly bypassing
      every Redis TTL in the system.

Usage (inside a tool):
    from backend.tools.market_data import get_shared_ticker

    yf_ticker = get_shared_ticker(ticker)
    hist = yf_ticker.history(period="1y")
"""

import logging
import threading
import time

import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How long a shared yf.Ticker instance may be reused before a fresh one is
# constructed. Long enough to comfortably cover one analysis pipeline run
# (all agents for one ticker, including the debate loop); short enough that
# a later, separate analysis still gets a fresh instance rather than
# indefinitely-stale in-memory data. Redis TTLs (900s-86400s depending on
# data type) remain the authority for how "fresh" cross-analysis data is —
# this is only about collapsing duplicate calls *within* one run.
_SHARED_TICKER_TTL_SECONDS: float = 120.0

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# ticker (normalised upper-case) -> (created_at monotonic timestamp, instance)
_ticker_cache: dict[str, tuple[float, yf.Ticker]] = {}


def _normalise(ticker: str) -> str:
    """Normalise a ticker symbol for use as a cache key."""
    return ticker.strip().upper()


def _evict_expired(now: float) -> None:
    """
    Drop cached entries older than ``_SHARED_TICKER_TTL_SECONDS``.

    Called with ``_lock`` already held. Doubles as the cache's only
    eviction mechanism, so a long-running server process never grows the
    cache unboundedly across many distinct tickers over time.
    """
    expired = [
        key
        for key, (created_at, _instance) in _ticker_cache.items()
        if now - created_at > _SHARED_TICKER_TTL_SECONDS
    ]
    for key in expired:
        del _ticker_cache[key]


def get_shared_ticker(ticker: str) -> yf.Ticker:
    """
    Return a shared ``yf.Ticker`` instance for ``ticker``.

    Constructs a new instance only on a cache miss (first call for this
    ticker, or the previous instance has aged past
    ``_SHARED_TICKER_TTL_SECONDS``). All calls for the same ticker within
    that window — regardless of which tool module makes them — receive
    the exact same object, so yfinance's own per-instance caching of
    ``.info`` / ``.financials`` / ``.balance_sheet`` / ``.cashflow`` /
    ``.history()`` is shared instead of duplicated.

    Thread-safe: LangGraph's parallel research-agent execution (Send API)
    may call this concurrently for the same ticker from multiple threads.

    Args:
        ticker: Stock ticker symbol, any case (e.g. 'tcs.ns', 'TCS.NS').

    Returns:
        A ``yf.Ticker`` instance. In normal operation this never raises —
        constructing a ``yf.Ticker`` does no network I/O in yfinance;
        failures surface later when the caller accesses a property such
        as ``.info`` or ``.history()``, exactly as before this change, so
        each tool's existing try/except handling around those property
        accesses is untouched. If construction itself ever does raise
        (e.g. a monkeypatched constructor in tests), the exception
        propagates to the caller unchanged and nothing is cached.
    """
    key = _normalise(ticker)
    now = time.monotonic()

    with _lock:
        _evict_expired(now)

        cached = _ticker_cache.get(key)
        if cached is not None:
            logger.debug("market_data: reusing shared yf.Ticker for %s", key)
            return cached[1]

        logger.info("market_data: constructing shared yf.Ticker for %s", key)
        instance = yf.Ticker(key)
        _ticker_cache[key] = (now, instance)
        return instance


def reset_shared_ticker_cache() -> None:
    """
    Clear the shared ``yf.Ticker`` cache.

    Used by test fixtures to guarantee isolation between tests that patch
    ``yf.Ticker`` with different mocks for the same ticker symbol. Safe to
    call at any time in application code too (e.g. between analyses if a
    caller wants to force fresh instances sooner than the TTL).
    """
    with _lock:
        _ticker_cache.clear()


def shared_ticker_cache_size() -> int:
    """
    Return the number of tickers currently cached.

    Exposed for tests and diagnostics only — not used in application
    control flow.
    """
    with _lock:
        return len(_ticker_cache)


__all__ = [
    "get_shared_ticker",
    "reset_shared_ticker_cache",
    "shared_ticker_cache_size",
]
