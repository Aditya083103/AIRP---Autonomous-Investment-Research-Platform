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
from typing import Any, Callable, TypeVar, cast

import pandas as pd
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from backend.services.rate_limiter import yfinance_throttle

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

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


# ---------------------------------------------------------------------------
# Retry-hardened yFinance accessors (Section A data-layer hardening, T-087)
# ---------------------------------------------------------------------------
#
# Root cause this section fixes: stock_price.py and financials.py used to
# access yf.Ticker's .history()/.info/.financials/.balance_sheet/.cashflow
# with no retry/back-off at all. On a cold run yFinance returns HTTP 429
# ("Too Many Requests") or an empty/partial payload, which cascaded into
# degraded Fundamental/Technical/Valuation output, a skewed committee
# weighting (portfolio_manager._compute_agent_weights), a verdict that
# could never reach BUY (portfolio_manager._determine_verdict), and a
# price target that was always "Not determined" -- see this project's
# refinement work order, Section A, for the full failure chain.
#
# These wrapper functions centralise the fix in the one module every tool
# (stock_price.py, financials.py, ratios.py) already funnels its yfinance
# access through via get_shared_ticker() above, mirroring the retry
# pattern already used in backend/tools/news.py
# (retry_if_exception_type/wait_exponential/before_sleep_log) but keyed on
# yFinance's own exceptions plus the HTTP status codes Section A calls out
# (429/403/503) rather than NewsAPI's.

# Retry policy: a bit more patient than news.py's (3 attempts, 2s-60s)
# because yFinance's rate limiting is typically shorter-lived and this
# path also has the process-wide throttle above reducing how often it
# gets hit in the first place. wait_exponential_jitter adds randomised
# jitter on top of the exponential back-off so multiple retrying agents
# don't all wake up and retry in lockstep.
_YF_RETRY_ATTEMPTS: int = 4
_YF_RETRY_WAIT_INITIAL_SECONDS: float = 2.0
_YF_RETRY_WAIT_MAX_SECONDS: float = 30.0

# HTTP status codes worth retrying: 429 (rate limited), 403 (Yahoo
# sometimes returns this for the same throttling condition instead of
# 429), 503 (upstream temporarily unavailable).
_RETRYABLE_HTTP_STATUS_CODES: frozenset[int] = frozenset({429, 403, 503})


def _is_retryable_yfinance_error(exc: BaseException) -> bool:
    """
    True for exceptions worth retrying: yFinance's own rate-limit
    exception, a timeout/connection error, or an HTTPError carrying one of
    _RETRYABLE_HTTP_STATUS_CODES. False for everything else (e.g. a
    genuinely invalid ticker, a programming error) so those fail fast
    instead of burning 4 retries on something back-off cannot fix.
    """
    if isinstance(exc, YFRateLimitError):
        return True
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code in _RETRYABLE_HTTP_STATUS_CODES
    return False


@retry(
    retry=retry_if_exception(_is_retryable_yfinance_error),
    wait=wait_exponential_jitter(
        initial=_YF_RETRY_WAIT_INITIAL_SECONDS, max=_YF_RETRY_WAIT_MAX_SECONDS
    ),
    stop=stop_after_attempt(_YF_RETRY_ATTEMPTS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_with_retry(fn: Callable[[], _T]) -> _T:
    """
    Run ``fn`` inside the process-wide yFinance concurrency throttle, with
    tenacity retry + exponential back-off + jitter on transient failures.

    ``fn`` takes no arguments -- callers pass a zero-arg closure (or bind
    args via a lambda) so this helper stays generic across .history(),
    .info, .financials, .balance_sheet, and .cashflow, which have
    different call shapes (a method call vs. a bare property access).
    """
    with yfinance_throttle.acquire():
        return fn()


def fetch_history(
    yf_ticker: yf.Ticker, period: str, auto_adjust: bool = True
) -> pd.DataFrame:
    """Retry-hardened wrapper around ``yf.Ticker.history()``."""
    return cast(
        pd.DataFrame,
        _call_with_retry(
            lambda: yf_ticker.history(period=period, auto_adjust=auto_adjust)
        ),
    )


def fetch_info(yf_ticker: yf.Ticker) -> dict[str, Any]:
    """Retry-hardened wrapper around the ``yf.Ticker.info`` property."""
    info = cast(dict[str, Any], _call_with_retry(lambda: yf_ticker.info))
    return info or {}


def fetch_income_statement_df(yf_ticker: yf.Ticker) -> pd.DataFrame:
    """Retry-hardened wrapper around the ``yf.Ticker.financials`` property."""
    return cast(pd.DataFrame, _call_with_retry(lambda: yf_ticker.financials))


def fetch_balance_sheet_df(yf_ticker: yf.Ticker) -> pd.DataFrame:
    """Retry-hardened wrapper around the ``yf.Ticker.balance_sheet`` property."""
    return cast(pd.DataFrame, _call_with_retry(lambda: yf_ticker.balance_sheet))


def fetch_cashflow_df(yf_ticker: yf.Ticker) -> pd.DataFrame:
    """Retry-hardened wrapper around the ``yf.Ticker.cashflow`` property."""
    return cast(pd.DataFrame, _call_with_retry(lambda: yf_ticker.cashflow))


__all__ = [
    "get_shared_ticker",
    "reset_shared_ticker_cache",
    "shared_ticker_cache_size",
    "fetch_history",
    "fetch_info",
    "fetch_income_statement_df",
    "fetch_balance_sheet_df",
    "fetch_cashflow_df",
]
