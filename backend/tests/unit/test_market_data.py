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

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_market_data.py -v
"""
import os

os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock, patch  # noqa: E402

from backend.tools.market_data import (  # noqa: E402
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
