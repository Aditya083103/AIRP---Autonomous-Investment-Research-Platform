# backend/tests/unit/test_market_data.py
"""
Unit tests for backend/tools/market_data.py — shared yFinance fetch layer
(backend hardening, post-Phase 6).

Coverage targets:
  * Two tools requesting the same ticker receive the identical yf.Ticker
    instance (single construction, multiple consumers).
  * A different ticker gets its own, separate instance.
  * The cache expires after its TTL, forcing a fresh construction.
  * reset_shared_ticker_cache() forces a fresh construction immediately.
  * Ticker symbols are normalised (case/whitespace) to the same cache key.
  * yf.Ticker() is called exactly once across a simulated multi-tool
    sequence for one ticker (stock_price -> financials -> ratios), the
    scenario T-061 exists to fix.
  * T-087 (Section A data-layer hardening): fetch_history/fetch_info/
    fetch_income_statement_df/fetch_balance_sheet_df/fetch_cashflow_df
    retry on 429/403/503/timeout/YFRateLimitError with back-off, do NOT
    retry non-retryable errors, and run inside the process-wide
    yfinance_throttle concurrency guard.

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_market_data.py -v
"""
import os

os.environ.setdefault("ENVIRONMENT", "test")

import threading  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import requests  # noqa: E402
from yfinance.exceptions import YFRateLimitError  # noqa: E402

from backend.tools import market_data  # noqa: E402
from backend.tools.market_data import (  # noqa: E402
    fetch_balance_sheet_df,
    fetch_cashflow_df,
    fetch_history,
    fetch_income_statement_df,
    fetch_info,
    get_shared_ticker,
    reset_shared_ticker_cache,
    shared_ticker_cache_size,
)

# ---------------------------------------------------------------------------
# Tests: get_shared_ticker — single-construction sharing
# ---------------------------------------------------------------------------


class TestGetSharedTicker:
    def test_same_ticker_returns_identical_instance(self) -> None:
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            first = get_shared_ticker("TCS.NS")
            second = get_shared_ticker("TCS.NS")

        assert first is second
        assert mock_ctor.call_count == 1

    def test_different_tickers_get_different_instances(self) -> None:
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            tcs = get_shared_ticker("TCS.NS")
            infy = get_shared_ticker("INFY.NS")

        assert tcs is not infy
        assert mock_ctor.call_count == 2

    def test_ticker_normalised_case_and_whitespace(self) -> None:
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            lower = get_shared_ticker("tcs.ns")
            upper = get_shared_ticker("TCS.NS")
            padded = get_shared_ticker("  TCS.NS  ")

        assert lower is upper is padded
        assert mock_ctor.call_count == 1
        # The single construction used the normalised symbol.
        mock_ctor.assert_called_once_with("TCS.NS")

    def test_three_tools_one_ticker_one_construction(self) -> None:
        """
        Simulates the exact T-061 scenario: stock_price.py, financials.py,
        and ratios.py each ask for the same ticker during one analysis.
        Before this module existed, this was 3 separate yf.Ticker()
        constructions (and up to 8-12 yfinance requests); now it is one.
        """
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")

            stock_price_ticker = get_shared_ticker("RELIANCE.NS")
            financials_ticker = get_shared_ticker("RELIANCE.NS")
            ratios_ticker = get_shared_ticker("RELIANCE.NS")

        assert stock_price_ticker is financials_ticker is ratios_ticker
        assert mock_ctor.call_count == 1

    def test_expired_entry_forces_fresh_construction(self) -> None:
        fake_time = [1_000.0]

        with (
            patch("backend.tools.market_data.yf.Ticker") as mock_ctor,
            patch(
                "backend.tools.market_data.time.monotonic",
                side_effect=lambda: fake_time[0],
            ),
            patch(
                "backend.tools.market_data._SHARED_TICKER_TTL_SECONDS",
                60.0,
            ),
        ):
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")

            first = get_shared_ticker("TCS.NS")
            fake_time[0] += 61.0  # advance past the (patched) 60s TTL
            second = get_shared_ticker("TCS.NS")

        assert first is not second
        assert mock_ctor.call_count == 2

    def test_within_ttl_reuses_instance(self) -> None:
        fake_time = [1_000.0]

        with (
            patch("backend.tools.market_data.yf.Ticker") as mock_ctor,
            patch(
                "backend.tools.market_data.time.monotonic",
                side_effect=lambda: fake_time[0],
            ),
            patch(
                "backend.tools.market_data._SHARED_TICKER_TTL_SECONDS",
                60.0,
            ),
        ):
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")

            first = get_shared_ticker("TCS.NS")
            fake_time[0] += 30.0  # still inside the 60s TTL
            second = get_shared_ticker("TCS.NS")

        assert first is second
        assert mock_ctor.call_count == 1

    def test_construction_failure_does_not_poison_cache(self) -> None:
        """
        If yf.Ticker() itself raises, the exception propagates (unchanged
        behaviour for callers) and nothing bad is cached — the next call
        gets a clean retry rather than silently returning a broken state.
        """
        with patch(
            "backend.tools.market_data.yf.Ticker",
            side_effect=RuntimeError("yfinance internal crash"),
        ):
            try:
                get_shared_ticker("TCS.NS")
            except RuntimeError:
                pass

        assert shared_ticker_cache_size() == 0

        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            get_shared_ticker("TCS.NS")

        assert shared_ticker_cache_size() == 1


# ---------------------------------------------------------------------------
# Tests: reset_shared_ticker_cache / shared_ticker_cache_size
# ---------------------------------------------------------------------------


class TestResetAndSize:
    def test_reset_clears_cache(self) -> None:
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            get_shared_ticker("TCS.NS")
            get_shared_ticker("INFY.NS")
            assert shared_ticker_cache_size() == 2

            reset_shared_ticker_cache()
            assert shared_ticker_cache_size() == 0

    def test_reset_forces_fresh_construction(self) -> None:
        with patch("backend.tools.market_data.yf.Ticker") as mock_ctor:
            mock_ctor.side_effect = lambda t: MagicMock(name=f"ticker-{t}")
            first = get_shared_ticker("TCS.NS")
            reset_shared_ticker_cache()
            second = get_shared_ticker("TCS.NS")

        assert first is not second
        assert mock_ctor.call_count == 2

    def test_size_starts_at_zero(self) -> None:
        # The autouse conftest fixture resets the cache before every test.
        assert shared_ticker_cache_size() == 0


# ---------------------------------------------------------------------------
# Tests: retry-hardened accessors (T-087, Section A)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_retry_sleep() -> None:
    """
    Eliminate tenacity's real exponential back-off sleep for every test in
    this module. Only affects tests that actually retry (the happy-path/
    non-retryable tests never call .sleep at all), so this is safe to
    apply unconditionally.
    """
    # tenacity's @retry decorator genuinely attaches a `.retry`
    # (BaseRetrying) attribute to the wrapped callable at runtime -- this
    # is tenacity's own documented pattern for overriding back-off sleep
    # in tests -- but its type stubs declare the decorator's return type
    # as a bare Callable, which has no `.retry` attribute statically.
    # Not fixable from our side: the attribute is real, only mypy's view
    # of tenacity's decorator type is incomplete.
    retrying = market_data._call_with_retry.retry  # type: ignore[attr-defined]
    retrying.sleep = lambda seconds: None


def _make_hist_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]},
        index=pd.date_range("2024-01-01", periods=1),
    )


class TestFetchHistoryRetryHardening:
    def test_recovers_after_rate_limit_then_succeeds(self) -> None:
        hist_df = _make_hist_df()
        calls = {"n": 0}

        def flaky_history(*args: object, **kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 3:
                raise YFRateLimitError()
            return hist_df

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = flaky_history

        result = fetch_history(mock_ticker, "1y")

        assert result is hist_df
        assert calls["n"] == 3

    def test_recovers_after_http_429(self) -> None:
        hist_df = _make_hist_df()
        calls = {"n": 0}
        response = MagicMock()
        response.status_code = 429

        def flaky_history(*args: object, **kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.HTTPError(response=response)
            return hist_df

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = flaky_history

        result = fetch_history(mock_ticker, "1y")

        assert result is hist_df
        assert calls["n"] == 2

    def test_gives_up_after_max_attempts_still_rate_limited(self) -> None:
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = YFRateLimitError()

        with pytest.raises(YFRateLimitError):
            fetch_history(mock_ticker, "1y")

        assert mock_ticker.history.call_count == market_data._YF_RETRY_ATTEMPTS

    def test_non_retryable_error_fails_immediately(self) -> None:
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = ValueError("not a rate-limit issue")

        with pytest.raises(ValueError):
            fetch_history(mock_ticker, "1y")

        assert mock_ticker.history.call_count == 1

    def test_non_retryable_http_status_fails_immediately(self) -> None:
        response = MagicMock()
        response.status_code = 404
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = requests.HTTPError(response=response)

        with pytest.raises(requests.HTTPError):
            fetch_history(mock_ticker, "1y")

        assert mock_ticker.history.call_count == 1


class TestFetchInfoRetryHardening:
    def test_recovers_after_timeout(self) -> None:
        calls = {"n": 0}
        info = {"longName": "Tata Consultancy Services Limited"}

        def flaky_info_getter() -> dict[str, str]:
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.Timeout("read timed out")
            return info

        mock_ticker = MagicMock()
        type(mock_ticker).info = property(lambda self: flaky_info_getter())

        result = fetch_info(mock_ticker)

        assert result == info
        assert calls["n"] == 2

    def test_none_info_becomes_empty_dict(self) -> None:
        mock_ticker = MagicMock()
        mock_ticker.info = None

        assert fetch_info(mock_ticker) == {}


class TestFinancialsAccessorsRetryHardening:
    def test_income_statement_retries_on_connection_error(self) -> None:
        income_df = pd.DataFrame({"Total Revenue": [100.0]})
        calls = {"n": 0}

        def flaky_financials() -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.ConnectionError("reset by peer")
            return income_df

        mock_ticker = MagicMock()
        type(mock_ticker).financials = property(lambda self: flaky_financials())

        result = fetch_income_statement_df(mock_ticker)

        assert result is income_df
        assert calls["n"] == 2

    def test_balance_sheet_retries_on_rate_limit(self) -> None:
        balance_df = pd.DataFrame({"Total Assets": [200.0]})
        calls = {"n": 0}

        def flaky_balance_sheet() -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 2:
                raise YFRateLimitError()
            return balance_df

        mock_ticker = MagicMock()
        type(mock_ticker).balance_sheet = property(lambda self: flaky_balance_sheet())

        result = fetch_balance_sheet_df(mock_ticker)

        assert result is balance_df
        assert calls["n"] == 2

    def test_cashflow_retries_on_service_unavailable(self) -> None:
        cashflow_df = pd.DataFrame({"Operating Cash Flow": [50.0]})
        calls = {"n": 0}
        response = MagicMock()
        response.status_code = 503

        def flaky_cashflow() -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.HTTPError(response=response)
            return cashflow_df

        mock_ticker = MagicMock()
        type(mock_ticker).cashflow = property(lambda self: flaky_cashflow())

        result = fetch_cashflow_df(mock_ticker)

        assert result is cashflow_df
        assert calls["n"] == 2


class TestYfinanceThrottleIntegration:
    def test_concurrent_calls_are_bounded_by_throttle(self) -> None:
        """
        Sanity check that fetch_history actually acquires the shared
        throttle (not just calling the underlying fn directly): with the
        throttle's max concurrency patched down to 1, two threads calling
        fetch_history at the same time must never overlap inside the
        guarded section.
        """
        from backend.services.rate_limiter import ConcurrencyThrottle

        single_slot_throttle = ConcurrencyThrottle(1)
        overlap_detected = threading.Event()
        currently_inside = {"n": 0}
        lock = threading.Lock()

        def slow_history(*args: object, **kwargs: object) -> pd.DataFrame:
            with lock:
                currently_inside["n"] += 1
                if currently_inside["n"] > 1:
                    overlap_detected.set()
            import time as _time

            _time.sleep(0.05)
            with lock:
                currently_inside["n"] -= 1
            return _make_hist_df()

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = slow_history

        with patch.object(market_data, "yfinance_throttle", single_slot_throttle):
            threads = [
                threading.Thread(target=fetch_history, args=(mock_ticker, "1y"))
                for _ in range(4)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert not overlap_detected.is_set()
