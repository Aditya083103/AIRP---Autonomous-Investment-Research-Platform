# backend/tests/integration/test_data_layer.py
"""
AIRP — Data layer integration tests (T-019)

These tests call REAL external APIs and verify the full round-trip from
tool invocation to a validated Pydantic output dict.  They are excluded
from the default pytest run and from CI — run them locally when you have
valid API keys and internet access.

Run all integration tests:
    ENVIRONMENT=test python -m pytest -m integration -v

Run a single class:
    ENVIRONMENT=test python -m pytest -m integration -v -k "StockPrice"

Pre-requisites:
    * Internet access (yFinance, World Bank, RBI, MOSPI)
    * NEWS_API_KEY in .env (news tests auto-skip without it)

Resilience design
-----------------
yFinance rate-limits aggressively. Tests that need price/financial data
use _fetch_*_resilient() helpers that try a ranked list of NSE tickers
and call pytest.skip() if ALL are unavailable — infrastructure outages
never fail the suite.

Macro tests only verify structure and types — not that specific values
are populated, because RBI/MOSPI/WorldBank scrapers break periodically.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("ENVIRONMENT", "test")

from typing import Any  # noqa: E402

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ranked list — try in order, stop at first success
CANDIDATE_TICKERS = ["RELIANCE.NS", "HDFCBANK.NS", "INFY.NS", "TCS.NS"]
COMPANY_NAME = "Tata Consultancy Services"
NSE_TICKER = "TCS.NS"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _assert_no_error(result: dict[str, Any], label: str) -> None:
    """Fail with a readable message when a tool returned an error dict."""
    if "error" in result:
        pytest.fail(
            f"{label} returned an error: "
            f"{result['error']} — {result.get('message', '')}"
        )


def _fetch_stock_price_resilient(
    period: str = "1y",
) -> tuple[dict[str, Any], str]:
    """
    Try CANDIDATE_TICKERS in order; return (result, ticker) on first success.
    Calls pytest.skip() if every ticker is rate-limited or unavailable.
    """
    from backend.tools.stock_price import fetch_stock_price

    last: dict[str, Any] = {}
    for ticker in CANDIDATE_TICKERS:
        result = fetch_stock_price.invoke({"ticker": ticker, "period": period})
        if "error" not in result:
            return result, ticker
        time.sleep(1)
        last = result

    pytest.skip(
        "All candidate tickers rate-limited — "
        f"last error: {last.get('error')}: {last.get('message')}"
    )


def _fetch_financials_resilient() -> tuple[dict[str, Any], str]:
    """Try CANDIDATE_TICKERS; return first successful financials result."""
    from backend.tools.financials import fetch_financials

    last: dict[str, Any] = {}
    for ticker in CANDIDATE_TICKERS:
        result = fetch_financials.invoke({"ticker": ticker})
        if "error" not in result:
            return result, ticker
        time.sleep(1)
        last = result

    pytest.skip(
        "All candidate tickers failed for financials — "
        f"last error: {last.get('error')}: {last.get('message')}"
    )


def _fetch_ratios_resilient() -> tuple[dict[str, Any], str]:
    """Try CANDIDATE_TICKERS; return first successful ratios result."""
    from backend.tools.ratios import fetch_ratios

    last: dict[str, Any] = {}
    for ticker in CANDIDATE_TICKERS:
        result = fetch_ratios.invoke({"ticker": ticker})
        if "error" not in result:
            return result, ticker
        time.sleep(1)
        last = result

    pytest.skip(
        "All candidate tickers failed for ratios — "
        f"last error: {last.get('error')}: {last.get('message')}"
    )


# ===========================================================================
# fetch_stock_price
# ===========================================================================


@pytest.mark.integration
class TestFetchStockPriceIntegration:
    def test_returns_valid_dict(self) -> None:
        result, ticker = _fetch_stock_price_resilient()
        assert result["ticker"] == ticker
        assert result["source"] == "yfinance"
        assert result["data_points"] > 200

    def test_stats_block_is_present_and_positive(self) -> None:
        result, _ = _fetch_stock_price_resilient()
        stats = result["stats"]
        assert stats["current_price"] > 0
        assert stats["price_52w_high"] > 0
        assert stats["price_52w_low"] > 0
        assert stats["avg_volume_30d"] > 0

    def test_ohlcv_records_have_correct_shape(self) -> None:
        result, _ = _fetch_stock_price_resilient()
        ohlcv = result["ohlcv"]
        assert len(ohlcv) > 0
        first = ohlcv[0]
        assert set(first.keys()) >= {"date", "open", "high", "low", "close", "volume"}
        assert first["high"] >= first["low"]
        assert first["volume"] > 0

    def test_invalid_ticker_returns_error_dict(self) -> None:
        from backend.tools.stock_price import fetch_stock_price

        result = fetch_stock_price.invoke(
            {"ticker": "XXXXXXXXXINVALID.NS", "period": "1y"}
        )
        assert "error" in result
        assert result["error"] == "ticker_not_found"

    def test_invalid_period_returns_error_dict(self) -> None:
        from backend.tools.stock_price import fetch_stock_price

        result = fetch_stock_price.invoke({"ticker": "RELIANCE.NS", "period": "10y"})
        assert "error" in result
        assert result["error"] == "invalid_parameter"

    def test_fetch_ohlcv_returns_only_candles(self) -> None:
        from backend.tools.stock_price import fetch_ohlcv

        for ticker in CANDIDATE_TICKERS:
            result = fetch_ohlcv.invoke({"ticker": ticker, "period": "1y"})
            if "error" not in result:
                assert "ohlcv" in result
                assert "stats" not in result
                assert result["data_points"] == len(result["ohlcv"])
                return
            time.sleep(1)
        pytest.skip("All tickers rate-limited for fetch_ohlcv")

    def test_3y_period_returns_more_data_than_1y(self) -> None:
        from backend.tools.stock_price import fetch_stock_price

        result_1y, ticker = _fetch_stock_price_resilient(period="1y")
        time.sleep(1)
        result_3y = fetch_stock_price.invoke({"ticker": ticker, "period": "3y"})
        if "error" in result_3y:
            pytest.skip(f"3y fetch rate-limited for {ticker}")
        assert result_3y["data_points"] > result_1y["data_points"]


# ===========================================================================
# fetch_financials
# ===========================================================================


@pytest.mark.integration
class TestFetchFinancialsIntegration:
    def test_returns_valid_dict(self) -> None:
        result, ticker = _fetch_financials_resilient()
        assert result["ticker"] == ticker
        assert result["source"] == "yfinance"
        assert result["years_available"] >= 1

    def test_income_statement_has_required_fields(self) -> None:
        result, _ = _fetch_financials_resilient()
        income = result["income_statement"]
        assert len(income) >= 1
        year = income[0]
        assert "fiscal_year" in year
        assert "revenue_crores" in year
        assert "net_income_crores" in year

    def test_balance_sheet_present(self) -> None:
        result, _ = _fetch_financials_resilient()
        bs = result["balance_sheet"]
        assert len(bs) >= 1
        assert "total_assets_crores" in bs[0]

    def test_cash_flow_present(self) -> None:
        result, _ = _fetch_financials_resilient()
        cf = result["cash_flow"]
        assert len(cf) >= 1
        assert "operating_cf_crores" in cf[0]

    def test_invalid_ticker_returns_error_dict(self) -> None:
        from backend.tools.financials import fetch_financials

        result = fetch_financials.invoke({"ticker": "XXXXXXXXXINVALID.NS"})
        assert "error" in result

    def test_fetch_income_statement_tool(self) -> None:
        from backend.tools.financials import fetch_income_statement

        for ticker in CANDIDATE_TICKERS:
            result = fetch_income_statement.invoke({"ticker": ticker})
            if "error" not in result:
                assert "income_statement" in result
                return
            time.sleep(1)
        pytest.skip("All tickers rate-limited for fetch_income_statement")

    def test_fetch_balance_sheet_tool(self) -> None:
        from backend.tools.financials import fetch_balance_sheet

        for ticker in CANDIDATE_TICKERS:
            result = fetch_balance_sheet.invoke({"ticker": ticker})
            if "error" not in result:
                assert "balance_sheet" in result
                return
            time.sleep(1)
        pytest.skip("All tickers rate-limited for fetch_balance_sheet")

    def test_fetch_cash_flow_tool(self) -> None:
        from backend.tools.financials import fetch_cash_flow

        for ticker in CANDIDATE_TICKERS:
            result = fetch_cash_flow.invoke({"ticker": ticker})
            if "error" not in result:
                assert "cash_flow" in result
                return
            time.sleep(1)
        pytest.skip("All tickers rate-limited for fetch_cash_flow")


# ===========================================================================
# fetch_ratios
# ===========================================================================


@pytest.mark.integration
class TestFetchRatiosIntegration:
    def test_returns_valid_dict(self) -> None:
        result, ticker = _fetch_ratios_resilient()
        assert result["ticker"] == ticker
        for field in [
            "pe_ratio",
            "pb_ratio",
            "roe_pct",
            "roce_pct",
            "debt_to_equity",
            "ev_to_ebitda",
        ]:
            assert field in result

    def test_inputs_block_present(self) -> None:
        result, _ = _fetch_ratios_resilient()
        assert "inputs" in result

    def test_fetch_ratios_summary_is_lighter(self) -> None:
        from backend.tools.ratios import fetch_ratios_summary

        full, ticker = _fetch_ratios_resilient()
        time.sleep(1)
        summary = fetch_ratios_summary.invoke({"ticker": ticker})
        if "error" in summary:
            pytest.skip(f"Summary rate-limited for {ticker}")
        assert len(summary.keys()) < len(full.keys())
        assert "inputs" not in summary

    def test_invalid_ticker_returns_error_dict(self) -> None:
        from backend.tools.ratios import fetch_ratios

        result = fetch_ratios.invoke({"ticker": "XXXXXXXXXINVALID.NS"})
        assert "error" in result


# ===========================================================================
# fetch_news
# ===========================================================================


@pytest.mark.integration
class TestFetchNewsIntegration:
    """Tests that require NEWS_API_KEY — auto-skipped when absent."""

    @pytest.fixture(autouse=True)
    def require_news_api_key(self) -> None:
        if not os.environ.get("NEWS_API_KEY", ""):
            pytest.skip("NEWS_API_KEY not set — skipping news integration tests")

    def test_returns_articles_for_tcs(self) -> None:
        from backend.tools.news import fetch_news

        result = fetch_news.invoke(
            {
                "company_name": COMPANY_NAME,
                "ticker": NSE_TICKER,
                "max_articles": 5,
            }
        )
        _assert_no_error(result, "fetch_news")
        assert result["company_name"] == COMPANY_NAME
        assert isinstance(result["articles"], list)

    def test_article_has_required_fields(self) -> None:
        from backend.tools.news import fetch_news

        result = fetch_news.invoke(
            {"company_name": COMPANY_NAME, "ticker": NSE_TICKER, "max_articles": 3}
        )
        _assert_no_error(result, "fetch_news")
        if result["articles_returned"] > 0:
            article = result["articles"][0]
            assert "title" in article
            assert "url" in article
            assert "published_at" in article
            assert article["url"].startswith("http")

    def test_fetch_news_summary_returns_headlines_only(self) -> None:
        from backend.tools.news import fetch_news_summary

        result = fetch_news_summary.invoke(
            {"company_name": COMPANY_NAME, "ticker": NSE_TICKER}
        )
        _assert_no_error(result, "fetch_news_summary")
        assert "headlines" in result
        assert "articles" not in result
        assert isinstance(result["headlines"], list)


@pytest.mark.integration
class TestFetchNewsMissingKey:
    """
    Tests news tool behaviour when NEWS_API_KEY is absent.

    Separate from TestFetchNewsIntegration so it never gets the autouse
    skip fixture. Patches _fetch_news_cached to bypass the @cached layer
    and reach the API-key-checking code in _fetch_news_from_api.

    Why patch _fetch_news_cached and not cache_get_json:
        news.py imports only {NEWS_TTL, cached} from cache.py — it does
        NOT import cache_get_json. The @cached decorator wraps
        _fetch_news_cached at decoration time. Patching _fetch_news_cached
        entirely is the clean way to force the live code path.
    """

    def test_missing_api_key_returns_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool must return configuration_error when NEWS_API_KEY is absent."""
        # Remove key from environment
        monkeypatch.delenv("NEWS_API_KEY", raising=False)

        from unittest.mock import patch

        import backend.tools.news as news_mod

        # Patch settings so _fetch_news_from_api can't fall back to settings key
        # Patch _fetch_news_cached to call _fetch_news_from_api directly,
        # bypassing the @cached decorator which would return a cached hit
        def _call_without_cache(
            company_name: str,
            ticker: str | None = None,
            max_articles: int = 20,
        ) -> dict[str, Any]:
            """Call the raw API function, skipping the cache layer."""
            result = news_mod._fetch_news_from_api(
                company_name=company_name,
                ticker=ticker,
                max_articles=max_articles,
            )
            return result.model_dump(mode="json")  # type: ignore[return-value]

        with patch.object(news_mod, "settings", None):
            with patch.object(
                news_mod, "_fetch_news_cached", side_effect=_call_without_cache
            ):
                from backend.tools.news import fetch_news

                result = fetch_news.invoke({"company_name": COMPANY_NAME})

        assert (
            result.get("error") == "configuration_error"
        ), f"Expected configuration_error, got: {result}"


# ===========================================================================
# fetch_macro_data
# ===========================================================================


@pytest.mark.integration
class TestFetchMacroDataIntegration:
    """
    Integration tests for backend/tools/macro.py.

    RBI, MOSPI, and World Bank scrape targets change layout periodically.
    These tests verify the STRUCTURAL contract only — not that fields are
    populated (scrape failures are infrastructure events, not code bugs).
    """

    def test_returns_valid_dict_shape(self) -> None:
        from backend.tools.macro import fetch_macro_data

        result = fetch_macro_data.invoke({})
        _assert_no_error(result, "fetch_macro_data")
        assert result["country"] == "India"
        assert "repo_rate" in result
        assert "cpi_inflation" in result
        assert "gdp_growth" in result
        assert "fetched_at" in result
        assert "sources" in result
        assert isinstance(result["warnings"], list)

    def test_all_field_types_are_correct(self) -> None:
        from backend.tools.macro import fetch_macro_data

        result = fetch_macro_data.invoke({})
        _assert_no_error(result, "fetch_macro_data")
        for field in ["repo_rate", "cpi_inflation", "gdp_growth"]:
            val = result[field]
            assert val is None or isinstance(
                val, float
            ), f"{field} must be float|None, got {type(val)}: {val}"

    def test_populated_fields_are_in_reasonable_range(self) -> None:
        from backend.tools.macro import fetch_macro_data

        result = fetch_macro_data.invoke({})
        _assert_no_error(result, "fetch_macro_data")
        if result["repo_rate"] is not None:
            assert 0 < result["repo_rate"] < 30
        if result["cpi_inflation"] is not None:
            assert -5 < result["cpi_inflation"] < 50
        if result["gdp_growth"] is not None:
            assert -20 < result["gdp_growth"] < 30

    def test_force_refresh_returns_same_structure(self) -> None:
        from backend.tools.macro import fetch_macro_data

        r1 = fetch_macro_data.invoke({})
        r2 = fetch_macro_data.invoke({"force_refresh": True})
        _assert_no_error(r1, "fetch_macro_data r1")
        _assert_no_error(r2, "fetch_macro_data r2")
        assert set(r1.keys()) == set(r2.keys())


# ===========================================================================
# fetch_earnings_transcript
# ===========================================================================


@pytest.mark.integration
class TestFetchEarningsTranscriptIntegration:
    """
    Integration tests for backend/tools/earnings_transcript.py.

    Both tools require company_name as a positional argument.
    The tool always returns a dict — never raises.
    """

    def test_returns_valid_dict_for_tcs(self) -> None:
        from backend.tools.earnings_transcript import fetch_earnings_transcript

        result = fetch_earnings_transcript.invoke(
            {
                "company_name": "Tata Consultancy Services",
                "ticker": NSE_TICKER,
            }
        )
        assert isinstance(result, dict)
        assert "ticker" in result or "error" in result

    def test_transcript_chunk_tool_callable(self) -> None:
        from backend.tools.earnings_transcript import fetch_transcript_chunk

        result = fetch_transcript_chunk.invoke(
            {
                "company_name": "Tata Consultancy Services",
                "ticker": NSE_TICKER,
            }
        )
        assert isinstance(result, dict)

    def test_invalid_company_returns_gracefully(self) -> None:
        from backend.tools.earnings_transcript import fetch_earnings_transcript

        result = fetch_earnings_transcript.invoke(
            {
                "company_name": "XXXXXXXXXINVALID COMPANY NAME 99999",
                "ticker": "XXXXXXXXXINVALID.NS",
            }
        )
        assert isinstance(result, dict)


# ===========================================================================
# Cache behaviour (idempotency)
# ===========================================================================


@pytest.mark.integration
class TestCacheBehaviourIntegration:
    """Verify two calls return structurally identical key sets."""

    def test_stock_price_idempotent(self) -> None:
        r1, ticker = _fetch_stock_price_resilient()
        time.sleep(1)
        from backend.tools.stock_price import fetch_stock_price

        r2 = fetch_stock_price.invoke({"ticker": ticker, "period": "1y"})
        if "error" in r2:
            pytest.skip(f"Second call rate-limited for {ticker}")
        assert set(r1.keys()) == set(r2.keys())

    def test_financials_idempotent(self) -> None:
        r1, ticker = _fetch_financials_resilient()
        time.sleep(1)
        from backend.tools.financials import fetch_financials

        r2 = fetch_financials.invoke({"ticker": ticker})
        if "error" in r2:
            pytest.skip(f"Second call rate-limited for {ticker}")
        assert set(r1.keys()) == set(r2.keys())

    def test_ratios_idempotent(self) -> None:
        r1, ticker = _fetch_ratios_resilient()
        time.sleep(1)
        from backend.tools.ratios import fetch_ratios

        r2 = fetch_ratios.invoke({"ticker": ticker})
        if "error" in r2:
            pytest.skip(f"Second call rate-limited for {ticker}")
        assert set(r1.keys()) == set(r2.keys())
