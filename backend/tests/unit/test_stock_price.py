# backend/tests/unit/test_stock_price.py
"""
Unit tests for backend/tools/stock_price.py — T-010

All yFinance calls are mocked via pytest-mock (mocker fixture) so these
tests run offline, in CI, and without consuming any real API quota.

Test coverage targets (acceptance criteria from T-010):
  ✓ fetch_stock_price returns a dict matching the StockPrice schema
  ✓ fetch_ohlcv returns only the candle series (no stats block)
  ✓ TickerNotFoundError raised (and gracefully handled) on empty DataFrame
  ✓ Invalid period string returns an error dict (not a crash)
  ✓ _fetch_from_yfinance raises TickerNotFoundError for invalid tickers
  ✓ PriceStats derived fields (MAs, % changes) computed correctly
  ✓ ticker normalisation (lowercase → uppercase)

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_stock_price.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
# The noqa: E402 comments on the imports below tell flake8 this ordering
# is intentional — the env var must exist before settings are read.
os.environ.setdefault("ENVIRONMENT", "test")

from datetime import date as Date  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any, cast  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.tools.stock_price import (  # noqa: E402
    OHLCVRecord,
    StockPrice,
    TickerNotFoundError,
    _build_stats,
    _compute_pct_change,
    _compute_sma,
    _fetch_from_yfinance,
    fetch_ohlcv,
    fetch_stock_price,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_hist_df(n_rows: int = 260) -> pd.DataFrame:
    """
    Build a synthetic yFinance history DataFrame with `n_rows` daily candles.
    Prices start at 3000 and increment by 1 per day so % changes are predictable.
    """
    dates = pd.date_range(end="2024-01-15", periods=n_rows, freq="B")
    prices = [3000.0 + i for i in range(n_rows)]
    return pd.DataFrame(
        {
            "Open": [p - 5.0 for p in prices],
            "High": [p + 10.0 for p in prices],
            "Low": [p - 10.0 for p in prices],
            "Close": prices,
            "Volume": [1_000_000 + i * 100 for i in range(n_rows)],
        },
        index=dates,
    )


def _make_ticker_mock(
    hist_df: pd.DataFrame, info: dict[str, Any] | None = None
) -> MagicMock:
    """Return a mocked yf.Ticker object."""
    mock = MagicMock()
    mock.history.return_value = hist_df
    mock.info = info or {
        "longName": "Tata Consultancy Services Limited",
        "exchange": "NSE",
        "currency": "INR",
    }
    return mock


@pytest.fixture
def mock_yf_ticker_valid() -> MagicMock:
    """Mocked yf.Ticker for TCS.NS with 260 days of data."""
    return _make_ticker_mock(_make_hist_df(260))


@pytest.fixture
def mock_yf_ticker_empty() -> MagicMock:
    """Mocked yf.Ticker that returns an empty DataFrame (ticker not found)."""
    mock = MagicMock()
    mock.history.return_value = pd.DataFrame()
    mock.info = {}
    return mock


@pytest.fixture
def mock_yf_ticker_sparse() -> MagicMock:
    """Mocked yf.Ticker with only 30 candles (not enough for 50d/200d MA)."""
    return _make_ticker_mock(_make_hist_df(30))


# ---------------------------------------------------------------------------
# Tests: _compute_pct_change (pure function — no mock needed)
# ---------------------------------------------------------------------------


class TestComputePctChange:
    def test_normal_positive_return(self) -> None:
        closes = [100.0, 110.0]
        result = _compute_pct_change(closes, lookback=1)
        assert result == pytest.approx(10.0, abs=0.01)

    def test_negative_return(self) -> None:
        closes = [100.0, 90.0]
        result = _compute_pct_change(closes, lookback=1)
        assert result == pytest.approx(-10.0, abs=0.01)

    def test_single_element_returns_zero(self) -> None:
        assert _compute_pct_change([100.0], lookback=5) == 0.0

    def test_empty_series_returns_zero(self) -> None:
        assert _compute_pct_change([], lookback=5) == 0.0

    def test_zero_start_price_returns_zero(self) -> None:
        assert _compute_pct_change([0.0, 100.0], lookback=1) == 0.0

    def test_lookback_capped_at_series_length(self) -> None:
        closes = [100.0, 200.0]
        result = _compute_pct_change(closes, lookback=999)
        assert result == pytest.approx(100.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: _compute_sma (pure function)
# ---------------------------------------------------------------------------


class TestComputeSma:
    def test_50_period_sma(self) -> None:
        closes = [float(i) for i in range(1, 51)]  # 1..50
        result = _compute_sma(closes, 50)
        assert result == pytest.approx(25.5, abs=0.01)

    def test_insufficient_data_returns_none(self) -> None:
        assert _compute_sma([100.0, 200.0], 50) is None

    def test_exact_window_size(self) -> None:
        closes = [10.0] * 50
        assert _compute_sma(closes, 50) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Tests: _build_stats
# ---------------------------------------------------------------------------


class TestBuildStats:
    def test_stats_from_260_records(self) -> None:
        hist = _make_hist_df(260)
        records: list[OHLCVRecord] = [
            OHLCVRecord(
                date=cast(pd.Timestamp, idx).date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            )
            for idx, row in hist.iterrows()
        ]
        stats = _build_stats(records)
        assert stats.current_price == pytest.approx(records[-1].close, abs=0.01)
        assert stats.ma_50d is not None
        assert stats.ma_200d is not None
        assert stats.above_ma_50d is not None

    def test_ma_none_when_insufficient_data(self) -> None:
        hist = _make_hist_df(30)
        records = [
            OHLCVRecord(
                date=cast(pd.Timestamp, idx).date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            )
            for idx, row in hist.iterrows()
        ]
        stats = _build_stats(records)
        assert stats.ma_50d is None
        assert stats.ma_200d is None
        assert stats.above_ma_50d is None
        assert stats.above_ma_200d is None


# ---------------------------------------------------------------------------
# Tests: _fetch_from_yfinance (yf.Ticker mocked)
# ---------------------------------------------------------------------------


class TestFetchFromYfinance:
    def test_returns_stock_price_model(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = _fetch_from_yfinance("TCS.NS", "1y")

        assert isinstance(result, StockPrice)
        assert result.ticker == "TCS.NS"
        assert result.period == "1y"
        assert result.source == "yfinance"
        assert result.data_points > 0
        assert len(result.ohlcv) == result.data_points

    def test_company_name_from_info(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = _fetch_from_yfinance("TCS.NS", "1y")
        assert result.company_name == "Tata Consultancy Services Limited"

    def test_ticker_uppercased(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = _fetch_from_yfinance("tcs.ns", "1y")
        assert result.ticker == "TCS.NS"

    def test_raises_ticker_not_found_on_empty_df(
        self, mock_yf_ticker_empty: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_empty
        ):
            with pytest.raises(TickerNotFoundError, match="INVALID.NS"):
                _fetch_from_yfinance("INVALID.NS", "1y")

    def test_raises_value_error_on_invalid_period(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            with pytest.raises(ValueError, match="Invalid period"):
                # "15y" is not in VALID_PERIODS -- "10y" was extended to
                # a valid horizon by T-085 and is covered separately by
                # test_all_periods_accepted below.
                _fetch_from_yfinance("TCS.NS", "15y")

    def test_exchange_and_currency_from_info(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = _fetch_from_yfinance("TCS.NS", "1y")
        assert result.exchange == "NSE"
        assert result.currency == "INR"

    def test_ohlcv_records_have_correct_types(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = _fetch_from_yfinance("TCS.NS", "1y")
        first = result.ohlcv[0]
        assert isinstance(first.date, Date)
        assert isinstance(first.open, float)
        assert isinstance(first.volume, int)

    def test_info_fetch_failure_uses_ticker_as_name(self) -> None:
        """If yf.Ticker.info is empty, company_name falls back to the ticker string."""
        mock = MagicMock()
        mock.history.return_value = _make_hist_df(260)
        mock.info = {}

        with patch("backend.tools.market_data.yf.Ticker", return_value=mock):
            result = _fetch_from_yfinance("RELIANCE.NS", "1y")
        assert result.company_name == "RELIANCE.NS"

    def test_all_periods_accepted(self, mock_yf_ticker_valid: MagicMock) -> None:
        # T-085: extended from ("1y", "3y", "5y") to the full analysis
        # horizon set now exposed on the AnalysisPage horizon selector.
        for period in ("1mo", "3mo", "6mo", "1y", "3y", "5y", "10y"):
            with patch(
                "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
            ):
                result = _fetch_from_yfinance("TCS.NS", period)
            assert result.period == period


# ---------------------------------------------------------------------------
# Tests: fetch_stock_price (LangChain @tool — tested via .invoke())
# ---------------------------------------------------------------------------


class TestFetchStockPriceTool:
    def test_tool_returns_dict_on_success(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})

        assert isinstance(result, dict)
        assert "error" not in result
        assert result["ticker"] == "TCS.NS"
        assert "stats" in result
        assert "ohlcv" in result

    def test_stats_keys_present(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})

        stats = result["stats"]
        expected_keys = {
            "current_price",
            "price_52w_high",
            "price_52w_low",
            "avg_volume_30d",
            "pct_change_1m",
            "pct_change_3m",
            "pct_change_1y",
            "ma_50d",
            "ma_200d",
            "above_ma_50d",
            "above_ma_200d",
        }
        assert expected_keys.issubset(stats.keys())

    def test_tool_returns_error_dict_on_ticker_not_found(
        self, mock_yf_ticker_empty: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_empty
        ):
            result = fetch_stock_price.invoke({"ticker": "FAKE.NS", "period": "1y"})

        assert result["error"] == "ticker_not_found"
        assert result["ticker"] == "FAKE.NS"
        assert "message" in result

    def test_tool_returns_error_dict_on_invalid_period(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            # "15y" is not in VALID_PERIODS -- "10y" was extended to a
            # valid horizon by T-085 (see TestFetchFromYfinance's
            # test_all_periods_accepted).
            result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "15y"})

        assert result["error"] == "invalid_parameter"

    def test_tool_default_period_is_1y(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_stock_price.invoke({"ticker": "TCS.NS"})
        assert result.get("period") == "1y"

    def test_ohlcv_list_is_not_empty(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_stock_price.invoke({"ticker": "INFY.NS", "period": "1y"})
        assert len(result["ohlcv"]) > 0

    def test_ohlcv_record_structure(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
        first_candle = result["ohlcv"][0]
        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in first_candle

    def test_unexpected_exception_returns_error_dict(self) -> None:
        mock = MagicMock()
        mock.history.side_effect = RuntimeError("yfinance internal error")
        with patch("backend.tools.market_data.yf.Ticker", return_value=mock):
            result = fetch_stock_price.invoke({"ticker": "TCS.NS", "period": "1y"})
        assert result["error"] == "unexpected_error"
        assert "TCS.NS" in result["ticker"]


# ---------------------------------------------------------------------------
# Tests: fetch_ohlcv (LangChain @tool)
# ---------------------------------------------------------------------------


class TestFetchOhlcvTool:
    def test_returns_only_candle_series(self, mock_yf_ticker_valid: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_ohlcv.invoke({"ticker": "TCS.NS", "period": "1y"})

        assert "ohlcv" in result
        assert "stats" not in result
        assert "ticker" in result
        assert "currency" in result
        assert "data_points" in result

    def test_error_on_empty_ticker(self, mock_yf_ticker_empty: MagicMock) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_empty
        ):
            result = fetch_ohlcv.invoke({"ticker": "XXXX.NS", "period": "1y"})
        assert result["error"] == "ticker_not_found"

    def test_data_points_matches_ohlcv_length(
        self, mock_yf_ticker_valid: MagicMock
    ) -> None:
        with patch(
            "backend.tools.market_data.yf.Ticker", return_value=mock_yf_ticker_valid
        ):
            result = fetch_ohlcv.invoke({"ticker": "TCS.NS", "period": "1y"})
        assert result["data_points"] == len(result["ohlcv"])


# ---------------------------------------------------------------------------
# Tests: Pydantic model validation
# ---------------------------------------------------------------------------


class TestStockPriceModelValidation:
    def test_empty_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            StockPrice(
                ticker="",
                company_name="Test",
                exchange="NSE",
                currency="INR",
                period="1y",
                data_points=1,
                first_date=Date.today(),
                last_date=Date.today(),
                stats=MagicMock(),
                ohlcv=[],
                fetched_at=datetime.utcnow(),
            )

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            StockPrice(
                ticker="TCS.NS",
                company_name="TCS",
                exchange="NSE",
                currency="INR",
                # "15y" is not in VALID_PERIODS -- "10y" was extended to
                # a valid horizon by T-085.
                period="15y",
                data_points=1,
                first_date=Date.today(),
                last_date=Date.today(),
                stats=MagicMock(),
                ohlcv=[],
                fetched_at=datetime.utcnow(),
            )

    def test_10y_period_now_valid(self) -> None:
        """T-085: '10y' is a newly-supported analysis horizon."""
        model = StockPrice(
            ticker="TCS.NS",
            company_name="TCS",
            exchange="NSE",
            currency="INR",
            period="10y",
            data_points=1,
            first_date=Date.today(),
            last_date=Date.today(),
            stats=MagicMock(),
            ohlcv=[],
            fetched_at=datetime.utcnow(),
        )
        assert model.period == "10y"
