# backend/tests/unit/test_ratios.py
"""
Unit tests for backend/tools/ratios.py — T-013

All yFinance and Alpha Vantage calls are mocked via unittest.mock.patch so
these tests run offline, in CI, and without consuming any real API quota.

Test coverage targets (acceptance criteria from T-013):
  ✓ All 6 ratios (PE, PB, ROE, ROCE, Debt/Equity, EV/EBITDA) computed
    correctly vs manual calculation for 3 test stocks (TCS, Infosys, Reliance)
  ✓ ROE / ROCE percentage precision preserved (single-step computation)
  ✓ fetch_ratios returns a dict matching the RatiosModel schema
  ✓ fetch_ratios_summary returns the six ratios only (no input breakdown)
  ✓ Non-positive denominators (zero/negative EPS, equity, EBITDA) → None
  ✓ Missing primitives → None ratio, no crash
  ✓ Alpha Vantage gap-fills a ratio yFinance could not compute
  ✓ Alpha Vantage 'Note' / 'Information' → rate-limit error (no retry sleep)
  ✓ Alpha Vantage 'Error Message' → AlphaVantageError
  ✓ Alpha Vantage string fields parsed (and ROE fraction scaled to percent)
  ✓ Completely empty data raises RatiosNotFoundError → error dict
  ✓ ticker normalised to uppercase

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_ratios.py -v
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from typing import Any  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.tools.ratios import (  # noqa: E402
    AlphaVantageError,
    AlphaVantageRateLimitError,
    RatioInputs,
    RatiosModel,
    RatiosNotFoundError,
    _build_inputs,
    _compute_ratios,
    _fetch_alpha_vantage_ratios,
    _fetch_ratios_from_sources,
    _handle_av_response,
    _parse_av_float,
    _parse_av_overview,
    _percentage,
    _ratio,
    _request_alpha_vantage,
    _safe_info_get,
    _statement_get,
    fetch_ratios,
    fetch_ratios_summary,
    reset_av_quota_breaker_for_tests,
)

# ---------------------------------------------------------------------------
# Test data — three real-world-scale stocks with hand-calculated ratios.
# All monetary figures are in the same absolute currency units (INR).
# ---------------------------------------------------------------------------

# (price, eps, bvps, net_income, equity, ebit, assets, curr_liab,
#  debt, cash, market_cap, ebitda)
_STOCKS: dict[str, RatioInputs] = {
    "TCS.NS": RatioInputs(
        price=3800,
        eps=130,
        book_value_per_share=270,
        shares_outstanding=3.6e9,
        net_income=4.6e11,
        total_equity=9.0e11,
        operating_income=5.8e11,
        total_assets=1.5e12,
        current_liabilities=4.0e11,
        total_debt=5.0e10,
        cash=3.0e11,
        market_cap=1.4e13,
        ebitda=6.2e11,
    ),
    "INFY.NS": RatioInputs(
        price=1500,
        eps=60,
        book_value_per_share=200,
        shares_outstanding=4.1e9,
        net_income=2.6e11,
        total_equity=8.6e11,
        operating_income=3.3e11,
        total_assets=1.25e12,
        current_liabilities=3.5e11,
        total_debt=8.0e10,
        cash=2.0e11,
        market_cap=6.2e12,
        ebitda=3.6e11,
    ),
    "RELIANCE.NS": RatioInputs(
        price=2900,
        eps=100,
        book_value_per_share=1200,
        shares_outstanding=6.8e9,
        net_income=7.0e11,
        total_equity=7.8e12,
        operating_income=1.4e12,
        total_assets=1.7e13,
        current_liabilities=4.0e12,
        total_debt=3.2e12,
        cash=9.0e11,
        market_cap=1.96e13,
        ebitda=1.8e12,
    ),
}

# Hand-calculated expected ratios (verified independently).
_EXPECTED: dict[str, dict[str, float]] = {
    "TCS.NS": {
        "pe_ratio": 29.23,
        "pb_ratio": 14.07,
        "roe_pct": 51.11,
        "roce_pct": 52.73,
        "debt_to_equity": 0.06,
        "ev_to_ebitda": 22.18,
    },
    "INFY.NS": {
        "pe_ratio": 25.0,
        "pb_ratio": 7.5,
        "roe_pct": 30.23,
        "roce_pct": 36.67,
        "debt_to_equity": 0.09,
        "ev_to_ebitda": 16.89,
    },
    "RELIANCE.NS": {
        "pe_ratio": 29.0,
        "pb_ratio": 2.42,
        "roe_pct": 8.97,
        "roce_pct": 10.77,
        "debt_to_equity": 0.41,
        "ev_to_ebitda": 12.17,
    },
}


def _make_ratios_ticker_mock(inputs: RatioInputs, currency: str = "INR") -> MagicMock:
    """Build a mocked yf.Ticker whose .info + statements yield `inputs`."""
    info = {
        "longName": "Mock Company Limited",
        "currency": currency,
        "financialCurrency": currency,
        "currentPrice": inputs.price,
        "trailingEps": inputs.eps,
        "bookValue": inputs.book_value_per_share,
        "sharesOutstanding": inputs.shares_outstanding,
        "marketCap": inputs.market_cap,
        "ebitda": inputs.ebitda,
        "totalDebt": inputs.total_debt,
        "totalCash": inputs.cash,
    }
    dates = pd.to_datetime(["2024-03-31"])
    balance_df = pd.DataFrame(
        {
            "Stockholders Equity": [inputs.total_equity],
            "Total Assets": [inputs.total_assets],
            "Current Liabilities": [inputs.current_liabilities],
            "Total Debt": [inputs.total_debt],
            "Cash And Cash Equivalents": [inputs.cash],
        },
        index=dates,
    ).T
    income_df = pd.DataFrame(
        {
            "Net Income": [inputs.net_income],
            "Operating Income": [inputs.operating_income],
            "EBITDA": [inputs.ebitda],
        },
        index=dates,
    ).T

    mock = MagicMock()
    mock.info = info
    mock.balance_sheet = balance_df
    mock.financials = income_df
    return mock


def _make_av_response(
    status_code: int = 200, body: dict[str, Any] | None = None
) -> MagicMock:
    """Build a mocked requests.Response for the Alpha Vantage endpoint."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body if body is not None else {"Symbol": "TCS"}
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Tests: pure division helpers
# ---------------------------------------------------------------------------


class TestRatioHelpers:
    def test_ratio_basic(self) -> None:
        assert _ratio(10.0, 4.0) == 2.5

    def test_ratio_none_numerator(self) -> None:
        assert _ratio(None, 4.0) is None

    def test_ratio_none_denominator(self) -> None:
        assert _ratio(10.0, None) is None

    def test_ratio_zero_denominator(self) -> None:
        assert _ratio(10.0, 0.0) is None

    def test_ratio_negative_denominator(self) -> None:
        assert _ratio(10.0, -4.0) is None

    def test_percentage_precision_preserved(self) -> None:
        # 46000 / 90000 = 0.5111... → 51.11%, NOT 51.0% (no premature rounding)
        assert _percentage(46000.0, 90000.0) == 51.11

    def test_percentage_zero_denominator(self) -> None:
        assert _percentage(10.0, 0.0) is None


# ---------------------------------------------------------------------------
# Tests: _safe_info_get / _statement_get
# ---------------------------------------------------------------------------


class TestSafeInfoGet:
    def test_returns_float(self) -> None:
        assert _safe_info_get({"marketCap": 1_000}, "marketCap") == 1000.0

    def test_missing_key_returns_none(self) -> None:
        assert _safe_info_get({}, "marketCap") is None

    def test_none_value_returns_none(self) -> None:
        assert _safe_info_get({"marketCap": None}, "marketCap") is None

    def test_non_numeric_returns_none(self) -> None:
        assert _safe_info_get({"marketCap": "n/a"}, "marketCap") is None

    def test_nan_returns_none(self) -> None:
        assert _safe_info_get({"marketCap": float("nan")}, "marketCap") is None


class TestStatementGet:
    def test_returns_most_recent_value(self) -> None:
        df = pd.DataFrame(
            {"Net Income": [100.0, 90.0]},
            index=pd.to_datetime(["2024-03-31", "2023-03-31"]),
        ).T
        assert _statement_get(df, "Net Income", 0) == 100.0

    def test_missing_row_returns_none(self) -> None:
        df = pd.DataFrame(
            {"Net Income": [100.0]}, index=pd.to_datetime(["2024-03-31"])
        ).T
        assert _statement_get(df, "Total Assets", 0) is None

    def test_empty_df_returns_none(self) -> None:
        assert _statement_get(pd.DataFrame(), "Net Income", 0) is None

    def test_none_df_returns_none(self) -> None:
        assert _statement_get(None, "Net Income", 0) is None

    def test_out_of_range_col_returns_none(self) -> None:
        df = pd.DataFrame(
            {"Net Income": [100.0]}, index=pd.to_datetime(["2024-03-31"])
        ).T
        assert _statement_get(df, "Net Income", 5) is None


# ---------------------------------------------------------------------------
# Tests: _compute_ratios — THE acceptance criterion (3 stocks vs manual calc)
# ---------------------------------------------------------------------------


class TestComputeRatios:
    @pytest.mark.parametrize("ticker", list(_STOCKS.keys()))
    def test_all_six_ratios_match_manual_calculation(self, ticker: str) -> None:
        computed = _compute_ratios(_STOCKS[ticker])
        expected = _EXPECTED[ticker]
        for key, value in expected.items():
            assert computed[key] == pytest.approx(
                value, abs=0.01
            ), f"{ticker} {key}: got {computed[key]}, expected {value}"

    def test_enterprise_value_derived(self) -> None:
        # EV = market_cap + total_debt - cash
        computed = _compute_ratios(_STOCKS["TCS.NS"])
        assert computed["enterprise_value"] == pytest.approx(1.375e13, rel=1e-6)

    def test_zero_eps_makes_pe_none(self) -> None:
        inputs = _STOCKS["TCS.NS"].model_copy(update={"eps": 0.0})
        assert _compute_ratios(inputs)["pe_ratio"] is None

    def test_negative_equity_makes_roe_and_de_none(self) -> None:
        inputs = _STOCKS["TCS.NS"].model_copy(update={"total_equity": -1.0e11})
        computed = _compute_ratios(inputs)
        assert computed["roe_pct"] is None
        assert computed["debt_to_equity"] is None

    def test_missing_inputs_make_ratios_none(self) -> None:
        computed = _compute_ratios(RatioInputs())
        for key in ("pe_ratio", "pb_ratio", "roe_pct", "roce_pct"):
            assert computed[key] is None


# ---------------------------------------------------------------------------
# Tests: Alpha Vantage parsing & response handling
# ---------------------------------------------------------------------------


class TestParseAvFloat:
    def test_numeric_string(self) -> None:
        assert _parse_av_float("25.43") == 25.43

    @pytest.mark.parametrize("raw", ["None", "-", "", "NaN", None])
    def test_missing_sentinels_return_none(self, raw: Any) -> None:
        assert _parse_av_float(raw) is None

    def test_invalid_text_returns_none(self) -> None:
        assert _parse_av_float("not-a-number") is None


class TestParseAvOverview:
    def test_maps_fields_and_scales_roe(self) -> None:
        payload = {
            "PERatio": "28.5",
            "PriceToBookRatio": "12.0",
            "ReturnOnEquityTTM": "0.45",  # fraction → 45.0%
            "EVToEBITDA": "20.1",
        }
        parsed = _parse_av_overview(payload)
        assert parsed["pe_ratio"] == 28.5
        assert parsed["pb_ratio"] == 12.0
        assert parsed["roe_pct"] == 45.0
        assert parsed["ev_to_ebitda"] == 20.1
        # ROCE and D/E are not exposed by the OVERVIEW endpoint
        assert parsed["roce_pct"] is None
        assert parsed["debt_to_equity"] is None


class TestHandleAvResponse:
    def test_note_raises_rate_limit(self) -> None:
        with pytest.raises(AlphaVantageRateLimitError):
            _handle_av_response({"Note": "throttled"})

    def test_information_raises_rate_limit(self) -> None:
        with pytest.raises(AlphaVantageRateLimitError):
            _handle_av_response({"Information": "limit reached"})

    def test_error_message_raises_av_error(self) -> None:
        with pytest.raises(AlphaVantageError, match="Invalid"):
            _handle_av_response({"Error Message": "Invalid API call"})

    def test_valid_payload_returned(self) -> None:
        payload = {"Symbol": "TCS", "PERatio": "28.5"}
        assert _handle_av_response(payload) == payload


class TestRequestAlphaVantage:
    def test_happy_path_returns_payload(self) -> None:
        body = {"Symbol": "TCS", "PERatio": "28.5"}
        with patch(
            "backend.tools.ratios.requests.get",
            return_value=_make_av_response(200, body),
        ):
            result = _request_alpha_vantage("TCS", "demo-key")
        assert result["Symbol"] == "TCS"


# ---------------------------------------------------------------------------
# Tests: _build_inputs
# ---------------------------------------------------------------------------


class TestBuildInputs:
    def test_pulls_from_info_and_statements(self) -> None:
        mock = _make_ratios_ticker_mock(_STOCKS["TCS.NS"])
        inputs = _build_inputs(mock.info, mock.balance_sheet, mock.financials)
        assert inputs.price == 3800
        assert inputs.total_equity == pytest.approx(9.0e11)
        assert inputs.operating_income == pytest.approx(5.8e11)


# ---------------------------------------------------------------------------
# Tests: _fetch_ratios_from_sources (yFinance mocked, Alpha Vantage controlled)
# ---------------------------------------------------------------------------


class TestFetchRatiosFromSources:
    def test_returns_ratios_model_with_correct_values(self) -> None:
        mock = _make_ratios_ticker_mock(_STOCKS["TCS.NS"])
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=mock),
            patch(
                "backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=None
            ),
        ):
            result = _fetch_ratios_from_sources("tcs.ns")

        assert isinstance(result, RatiosModel)
        assert result.ticker == "TCS.NS"  # normalised to uppercase
        assert result.pe_ratio == pytest.approx(29.23, abs=0.01)
        assert result.pb_ratio == pytest.approx(14.07, abs=0.01)
        assert result.roe_pct == pytest.approx(51.11, abs=0.01)
        assert result.roce_pct == pytest.approx(52.73, abs=0.01)
        assert result.debt_to_equity == pytest.approx(0.06, abs=0.01)
        assert result.ev_to_ebitda == pytest.approx(22.18, abs=0.01)
        # All six were computed from yFinance, not Alpha Vantage
        assert all(result.sources[k] == "computed" for k in _EXPECTED["TCS.NS"])

    def test_alpha_vantage_fills_a_gap(self) -> None:
        # yFinance lacks EBITDA → ev_to_ebitda cannot be computed; AV supplies it.
        inputs = _STOCKS["TCS.NS"].model_copy(update={"ebitda": None})
        mock = _make_ratios_ticker_mock(inputs)
        mock.info["ebitda"] = None  # ensure info has no fallback either
        av = {
            "pe_ratio": None,
            "pb_ratio": None,
            "roe_pct": None,
            "roce_pct": None,
            "debt_to_equity": None,
            "ev_to_ebitda": 21.5,
        }
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=mock),
            patch("backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=av),
        ):
            result = _fetch_ratios_from_sources("TCS.NS")

        assert result.ev_to_ebitda == 21.5
        assert result.sources["ev_to_ebitda"] == "alpha_vantage"
        assert result.sources["pe_ratio"] == "computed"

    def test_empty_data_raises_not_found(self) -> None:
        empty = MagicMock()
        empty.info = {}
        empty.balance_sheet = pd.DataFrame()
        empty.financials = pd.DataFrame()
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=empty),
            patch(
                "backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=None
            ),
        ):
            with pytest.raises(RatiosNotFoundError):
                _fetch_ratios_from_sources("BADTICKER")


# ---------------------------------------------------------------------------
# Tests: fetch_ratios / fetch_ratios_summary LangChain tools
# ---------------------------------------------------------------------------


class TestFetchRatiosTool:
    def test_returns_dict_matching_schema(self) -> None:
        mock = _make_ratios_ticker_mock(_STOCKS["INFY.NS"])
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=mock),
            patch(
                "backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=None
            ),
        ):
            result = fetch_ratios.invoke({"ticker": "INFY.NS"})

        expected_keys = {
            "ticker",
            "company_name",
            "currency",
            "pe_ratio",
            "pb_ratio",
            "roe_pct",
            "roce_pct",
            "debt_to_equity",
            "ev_to_ebitda",
            "enterprise_value",
            "inputs",
            "sources",
            "fetched_at",
            "source",
            "data_warnings",
        }
        assert expected_keys.issubset(result.keys())
        assert result["pe_ratio"] == pytest.approx(25.0, abs=0.01)
        assert "error" not in result

    def test_not_found_returns_error_dict(self) -> None:
        empty = MagicMock()
        empty.info = {}
        empty.balance_sheet = pd.DataFrame()
        empty.financials = pd.DataFrame()
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=empty),
            patch(
                "backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=None
            ),
        ):
            result = fetch_ratios.invoke({"ticker": "nope"})
        assert result["error"] == "ratios_not_found"
        assert result["ticker"] == "NOPE"

    def test_summary_returns_six_ratios_only(self) -> None:
        mock = _make_ratios_ticker_mock(_STOCKS["RELIANCE.NS"])
        with (
            patch("backend.tools.market_data.yf.Ticker", return_value=mock),
            patch(
                "backend.tools.ratios._fetch_alpha_vantage_ratios", return_value=None
            ),
        ):
            result = fetch_ratios_summary.invoke({"ticker": "RELIANCE.NS"})

        assert "inputs" not in result
        assert "sources" not in result
        assert result["debt_to_equity"] == pytest.approx(0.41, abs=0.01)
        assert result["roe_pct"] == pytest.approx(8.97, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: Alpha Vantage retry policy + same-day circuit breaker
#
# Regression tests for a real production bug: stop_after_attempt(3) used to
# retry on AlphaVantageRateLimitError itself, meaning a single rate-limited
# fetch_ratios call burned 3 of the 25 daily requests instead of 1, and
# every subsequent ticker rediscovered the same exhaustion with its own
# live round-trip. See ratios.py's docstrings on the retry decorator and
# on _av_quota_exhausted_date for the full rationale.
# ---------------------------------------------------------------------------


class TestAlphaVantageRetryPolicy:
    def setup_method(self) -> None:
        reset_av_quota_breaker_for_tests()

    def teardown_method(self) -> None:
        reset_av_quota_breaker_for_tests()

    def test_rate_limit_note_is_not_retried(self) -> None:
        """A 'Note' rate-limit response must fail on the first attempt --
        no tenacity retry, no sleep, and critically no 2nd/3rd real HTTP
        request wasted against the same daily quota."""
        with patch(
            "backend.tools.ratios.requests.get",
            return_value=_make_av_response(200, {"Note": "throttled"}),
        ) as mock_get:
            with pytest.raises(AlphaVantageRateLimitError):
                _request_alpha_vantage("TCS", "demo-key")
        assert mock_get.call_count == 1

    def test_information_rate_limit_is_not_retried(self) -> None:
        with patch(
            "backend.tools.ratios.requests.get",
            return_value=_make_av_response(200, {"Information": "limit reached"}),
        ) as mock_get:
            with pytest.raises(AlphaVantageRateLimitError):
                _request_alpha_vantage("TCS", "demo-key")
        assert mock_get.call_count == 1


class TestAlphaVantageQuotaBreaker:
    def setup_method(self) -> None:
        reset_av_quota_breaker_for_tests()

    def teardown_method(self) -> None:
        reset_av_quota_breaker_for_tests()

    def test_first_rate_limited_call_hits_the_network(self) -> None:
        with (
            patch.dict(os.environ, {"ALPHA_VANTAGE_KEY": "demo-key"}),
            patch(
                "backend.tools.ratios.requests.get",
                return_value=_make_av_response(200, {"Note": "throttled"}),
            ) as mock_get,
        ):
            result = _fetch_alpha_vantage_ratios("TCS.NS")

        assert result is None
        assert mock_get.call_count == 1

    def test_second_ticker_after_exhaustion_skips_the_network_entirely(self) -> None:
        """Once one call confirms the daily quota is gone, a different
        ticker later in the same run must not make its own live request --
        that request is certain to fail identically until UTC midnight."""
        with (
            patch.dict(os.environ, {"ALPHA_VANTAGE_KEY": "demo-key"}),
            patch(
                "backend.tools.ratios.requests.get",
                return_value=_make_av_response(200, {"Note": "throttled"}),
            ) as mock_get,
        ):
            _fetch_alpha_vantage_ratios("TCS.NS")  # 1st call -- latches the breaker
            result = _fetch_alpha_vantage_ratios("INFY.NS")  # 2nd call -- should skip

        assert result is None
        assert mock_get.call_count == 1

    def test_breaker_reset_allows_calls_again(self) -> None:
        """Sanity check on the test helper itself: resetting the breaker
        (simulating a new day) lets live calls happen again."""
        with (
            patch.dict(os.environ, {"ALPHA_VANTAGE_KEY": "demo-key"}),
            patch(
                "backend.tools.ratios.requests.get",
                return_value=_make_av_response(200, {"Note": "throttled"}),
            ) as mock_get,
        ):
            _fetch_alpha_vantage_ratios("TCS.NS")
            reset_av_quota_breaker_for_tests()
            _fetch_alpha_vantage_ratios("INFY.NS")

        assert mock_get.call_count == 2
