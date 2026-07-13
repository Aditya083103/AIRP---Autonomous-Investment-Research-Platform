# backend/tests/unit/test_research_agents.py
"""
Unit tests for T-027: All 4 Research Agents — Consolidated Suite.

Task: Write unit tests for all 4 research agents.
Strategy: Mock all tool calls; test output schema validation;
          test error handling when tools return empty data.
Acceptance criteria: >85% coverage; all schema validations tested;
                     error paths covered.

This file is a COMPLEMENT to the individual agent test files
(test_fundamental_analyst.py, test_technical_analyst.py,
test_sentiment_analyst.py, test_macro_economist.py).  It focuses on
three coverage gap areas that the individual files do not fully address:

  GAP 1 — Schema validation
    Pydantic ValidationError is raised when required fields are missing
    or constrained numeric fields are out of range.  Tests verify the
    output model contracts that agents must honour.

  GAP 2 — Empty / sparse data paths
    Tools returning {} (no error key, no data keys) or minimal data
    structures must never crash an agent.  Agents must degrade gracefully
    and return a valid model with sensible defaults.

  GAP 3 — Cross-agent consistency
    All four agents share the AgentOutput base class contract.
    Tests verify that every agent's node function returns the expected
    state dict key and that the serialised output is JSON-safe.

Test classes:
  TestFundamentalAnalystSchemaValidation   -- Pydantic constraints on FA output
  TestFundamentalAnalystEmptyData          -- tools return {} / sparse data
  TestFundamentalAnalystErrorPaths         -- exception from tool.invoke()
  TestTechnicalAnalystSchemaValidation     -- Pydantic constraints on TA output
  TestTechnicalAnalystEmptyData            -- empty OHLCV, single candle
  TestTechnicalAnalystErrorPaths           -- tool raises / price data errors
  TestSentimentAnalystSchemaValidation     -- Pydantic constraints on SA output
  TestSentimentAnalystEmptyData            -- zero articles, empty text
  TestSentimentAnalystErrorPaths           -- fetch_news raises exception
  TestMacroAnalystSchemaValidation         -- Pydantic constraints on MA output
  TestMacroAnalystEmptyData                -- all-None macro data
  TestMacroAnalystErrorPaths               -- fetch_macro_data raises
  TestAllAgentsNodeContract                -- state dict / JSON-safe contract
  TestAllAgentsTracingIntegration          -- @traced_agent __wrapped__ check

All external calls (yFinance, NewsAPI, RBI, ChromaDB, Groq) are mocked.
No network. No database. No LLM quota consumed.
"""
from __future__ import annotations

import json
import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

from pydantic import ValidationError  # noqa: E402
import pytest  # noqa: E402

from backend.agents.output_models import (  # noqa: E402
    FundamentalAnalysis,
    MacroAnalysis,
    SentimentAnalysis,
    TechnicalAnalysis,
)

# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------

_BASE_KWARGS: dict[str, Any] = {
    "analysis_id": "t027-test-uuid",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}


def _make_llm(content: str = "") -> MagicMock:
    """Return a mock LLM whose .invoke() returns a MagicMock with .content."""
    m = MagicMock()
    m.invoke.return_value = MagicMock(content=content)
    return m


def _make_llm_raises(exc: Exception) -> MagicMock:
    """Return a mock LLM whose .invoke() raises exc."""
    m = MagicMock()
    m.invoke.side_effect = exc
    return m


# ---------------------------------------------------------------------------
# Minimal valid tool responses (enough for agents to succeed)
# ---------------------------------------------------------------------------

_FINANCIALS_MINIMAL: dict[str, Any] = {
    "income_statement": [
        {
            "fiscal_year": "FY 2024",
            "revenue_crores": 240_890.0,
            "net_income_crores": 46_099.0,
            "gross_profit_crores": 86_000.0,
            "operating_income_crores": 59_000.0,
            "net_margin_pct": 19.1,
            "operating_margin_pct": 24.5,
            "gross_margin_pct": 35.7,
        },
        {
            "fiscal_year": "FY 2021",
            "revenue_crores": 164_000.0,
            "net_income_crores": 33_000.0,
            "net_margin_pct": 20.1,
            "operating_margin_pct": 25.5,
            "gross_margin_pct": 37.0,
        },
    ],
    "balance_sheet": [
        {
            "fiscal_year": "FY 2024",
            "total_debt_crores": 2_000.0,
            "cash_crores": 30_000.0,
            "total_equity_crores": 90_000.0,
            "debt_to_equity": 0.02,
            "current_ratio": 2.1,
        }
    ],
    "cash_flow": [
        {
            "fiscal_year": "FY 2024",
            "free_cash_flow_crores": 44_000.0,
            "fcf_margin_pct": 18.3,
            "operating_cash_flow_crores": 50_000.0,
        }
    ],
    "data_warnings": [],
}

_RATIOS_MINIMAL: dict[str, Any] = {
    "pe_ratio": 28.5,
    "pb_ratio": 9.2,
    "roe_pct": 46.2,
    "roce_pct": 51.1,
    "debt_to_equity": 0.02,
    "ev_to_ebitda": 19.5,
    "data_warnings": [],
}

_FA_LLM_JSON = json.dumps(
    {
        "strengths": ["Revenue CAGR of 13.7%", "ROE 46.2%"],
        "risks": ["PE 28.5x premium"],
        "summary": "Strong fundamentals with a score of 9/10.",
    }
)

# 260 synthetic closes for technical analyst
_CLOSES_260 = [3000.0 + float(i) for i in range(260)]
_OHLCV_260 = [
    {
        "date": f"2024-{(i // 30) + 1:02d}-01",
        "open": round(c - 2.0, 2),
        "high": round(c + 5.0, 2),
        "low": round(c - 5.0, 2),
        "close": round(c, 2),
        "volume": 1_000_000 + i * 500,
    }
    for i, c in enumerate(_CLOSES_260)
]

_PRICE_DATA_GOOD: dict[str, Any] = {
    "ticker": "TCS.NS",
    "company_name": "Tata Consultancy Services",
    "period": "1y",
    "data_points": 260,
    "stats": {
        "current_price": 3259.0,
        "price_52w_high": 3259.0,
        "price_52w_low": 3000.0,
        "avg_volume_30d": 1_040_000,
    },
    "ohlcv": _OHLCV_260,
}

_TA_LLM_JSON = json.dumps({"summary": "TCS shows a BUY signal with RSI at 62."})

_NEWS_POSITIVE: list[dict[str, Any]] = [
    {
        "title": "TCS records best quarterly profit",
        "description": "Strong growth in cloud services drove revenues up.",
        "published_at": "2024-01-15",
    },
    {
        "title": "TCS wins major deal",
        "description": "Record order inflow for the year.",
        "published_at": "2024-01-10",
    },
]

_NEWS_RESULT_GOOD: dict[str, Any] = {
    "company_name": "TCS",
    "articles": _NEWS_POSITIVE,
    "total_results": 2,
}

_SA_LLM_JSON = json.dumps(
    {
        "top_positive_headlines": ["TCS records best quarterly profit"],
        "top_negative_headlines": [],
        "dominant_topics": ["deal wins", "profit growth"],
        "red_flags": [],
        "summary": "TCS sentiment is very positive over the last 30 days.",
    }
)

_MACRO_RESULT_GOOD: dict[str, Any] = {
    "repo_rate": 6.5,
    "cpi_inflation": 5.1,
    "gdp_growth": 7.2,
    "repo_rate_as_of": "2024-01-01",
    "cpi_as_of": "2024-01-01",
    "gdp_as_of": "2023",
    "warnings": [],
    "cached": False,
}

_MA_LLM_JSON = json.dumps(
    {
        "tailwinds": ["Strong GDP supports demand"],
        "headwinds": ["Calibrated tightening mild pressure"],
        "global_factors": ["Fed rate pause reduces EM risk"],
        "india_specific": ["RBI rate at 6.5%"],
        "summary": "Macro environment is broadly favourable for IT sector.",
    }
)


# ---------------------------------------------------------------------------
# GAP 1: Schema Validation Tests
# ---------------------------------------------------------------------------


class TestFundamentalAnalystSchemaValidation:
    """
    Verify Pydantic v2 constraints on FundamentalAnalysis.
    Acceptance criteria: all schema validations tested.
    """

    def test_score_below_minimum_raises(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalAnalysis(**_BASE_KWARGS, score=0)

    def test_score_above_maximum_raises(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalAnalysis(**_BASE_KWARGS, score=11)

    def test_score_exactly_1_is_valid(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=1)
        assert m.score == 1

    def test_score_exactly_10_is_valid(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=10)
        assert m.score == 10

    def test_missing_score_defaults_to_none(self) -> None:
        """
        T-081: score became Optional[int] with default None (an absent
        score legitimately means 'insufficient data', not a validation
        error), so constructing without it must succeed rather than raise.
        """
        m = FundamentalAnalysis.model_validate({**_BASE_KWARGS})
        assert m.score is None

    def test_missing_analysis_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalAnalysis.model_validate(
                {"company_name": "TCS", "ticker": "TCS.NS", "score": 7}
            )

    def test_missing_ticker_raises(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalAnalysis.model_validate(
                {"analysis_id": "x", "company_name": "TCS", "score": 7}
            )

    def test_optional_fields_default_none(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        assert m.revenue_growth_pct is None
        assert m.gross_margin_pct is None
        assert m.free_cash_flow_cr is None
        assert m.debt_to_equity is None
        assert m.roe_pct is None

    def test_list_fields_default_empty(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        assert m.strengths == []
        assert m.weaknesses == []

    def test_summary_defaults_empty_string(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        assert m.summary == ""

    def test_error_field_defaults_none(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        assert m.error is None

    def test_error_field_accepts_string(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=1, error="fetch failed")
        assert m.error == "fetch failed"

    def test_agent_name_default(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        assert m.agent_name == "fundamental_analyst"

    def test_frozen_model_immutable(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        with pytest.raises(ValidationError):
            m.score = 9  # type: ignore[misc]

    def test_model_dump_json_safe(self) -> None:
        m = FundamentalAnalysis(**_BASE_KWARGS, score=7)
        dumped = json.dumps(m.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_model_json_schema_non_empty(self) -> None:
        schema = FundamentalAnalysis.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema


class TestTechnicalAnalystSchemaValidation:
    """Verify Pydantic v2 constraints on TechnicalAnalysis."""

    def test_signal_strength_below_min_raises(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalAnalysis(**_BASE_KWARGS, signal="BUY", signal_strength=0)

    def test_signal_strength_above_max_raises(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalAnalysis(**_BASE_KWARGS, signal="BUY", signal_strength=11)

    def test_signal_strength_1_valid(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="HOLD", signal_strength=1)
        assert m.signal_strength == 1

    def test_signal_strength_10_valid(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="SELL", signal_strength=10)
        assert m.signal_strength == 10

    def test_missing_signal_raises(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalAnalysis.model_validate({**_BASE_KWARGS, "signal_strength": 5})

    def test_missing_signal_strength_raises(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalAnalysis.model_validate({**_BASE_KWARGS, "signal": "BUY"})

    def test_optional_price_fields_default_none(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="HOLD", signal_strength=5)
        assert m.current_price is None
        assert m.ma_50d is None
        assert m.rsi_14 is None

    def test_list_fields_default_empty(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="HOLD", signal_strength=5)
        assert m.support_levels == []
        assert m.resistance_levels == []

    def test_agent_name_default(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="BUY", signal_strength=7)
        assert m.agent_name == "technical_analyst"

    def test_model_dump_json_safe(self) -> None:
        m = TechnicalAnalysis(**_BASE_KWARGS, signal="BUY", signal_strength=7)
        dumped = json.dumps(m.model_dump(mode="json"))
        assert isinstance(dumped, str)


class TestSentimentAnalystSchemaValidation:
    """Verify Pydantic v2 constraints on SentimentAnalysis."""

    def _minimal(self, **extra: Any) -> SentimentAnalysis:
        defaults: dict[str, Any] = {
            "sentiment_score": 0.0,
            "sentiment_label": "neutral",
            "articles_analysed": 0,
            "positive_articles": 0,
            "negative_articles": 0,
            "neutral_articles": 0,
        }
        return SentimentAnalysis(**_BASE_KWARGS, **{**defaults, **extra})

    def test_sentiment_score_above_max_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal(sentiment_score=1.1)

    def test_sentiment_score_below_min_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal(sentiment_score=-1.1)

    def test_sentiment_score_exact_max_valid(self) -> None:
        m = self._minimal(sentiment_score=1.0)
        assert m.sentiment_score == pytest.approx(1.0)

    def test_sentiment_score_exact_min_valid(self) -> None:
        m = self._minimal(sentiment_score=-1.0)
        assert m.sentiment_score == pytest.approx(-1.0)

    def test_articles_analysed_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal(articles_analysed=-1)

    def test_missing_sentiment_score_raises(self) -> None:
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(
                {
                    **_BASE_KWARGS,
                    "sentiment_label": "neutral",
                    "articles_analysed": 0,
                    "positive_articles": 0,
                    "negative_articles": 0,
                    "neutral_articles": 0,
                }
            )

    def test_red_flags_defaults_empty(self) -> None:
        m = self._minimal()
        assert m.red_flags == []
        assert m.red_flag_count == 0

    def test_agent_name_default(self) -> None:
        m = self._minimal()
        assert m.agent_name == "news_sentiment"

    def test_model_dump_json_safe(self) -> None:
        m = self._minimal(sentiment_score=0.5, sentiment_label="positive")
        dumped = json.dumps(m.model_dump(mode="json"))
        assert isinstance(dumped, str)


class TestMacroAnalystSchemaValidation:
    """Verify Pydantic v2 constraints on MacroAnalysis."""

    def _minimal(self, **extra: Any) -> MacroAnalysis:
        defaults: dict[str, Any] = {
            "macro_environment": "neutral",
            "sector_impact": "neutral",
        }
        return MacroAnalysis(**_BASE_KWARGS, **{**defaults, **extra})

    def test_missing_macro_environment_raises(self) -> None:
        with pytest.raises(ValidationError):
            MacroAnalysis.model_validate({**_BASE_KWARGS, "sector_impact": "neutral"})

    def test_missing_sector_impact_raises(self) -> None:
        with pytest.raises(ValidationError):
            MacroAnalysis.model_validate(
                {**_BASE_KWARGS, "macro_environment": "neutral"}
            )

    def test_optional_rate_fields_default_none(self) -> None:
        m = self._minimal()
        assert m.rbi_repo_rate_pct is None
        assert m.rate_stance is None
        assert m.cpi_inflation_pct is None
        assert m.gdp_growth_pct is None

    def test_list_fields_default_empty(self) -> None:
        m = self._minimal()
        assert m.tailwinds == []
        assert m.headwinds == []

    def test_agent_name_default(self) -> None:
        m = self._minimal()
        assert m.agent_name == "macro_economist"

    def test_model_dump_json_safe(self) -> None:
        m = self._minimal()
        dumped = json.dumps(m.model_dump(mode="json"))
        assert isinstance(dumped, str)


# ---------------------------------------------------------------------------
# GAP 2: Empty / Sparse Data Paths
# ---------------------------------------------------------------------------


class TestFundamentalAnalystEmptyData:
    """
    Agent must not crash when tools return empty or sparse data structures.
    Acceptance criteria: error paths covered; model always returned.
    """

    def _run(
        self,
        financials: dict[str, Any],
        ratios: dict[str, Any],
        llm_json: str = _FA_LLM_JSON,
    ) -> FundamentalAnalysis:
        from backend.agents.fundamental_analyst import _run_fundamental_analysis_core

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=_make_llm(llm_json),
            ),
        ):
            mock_fin.invoke.return_value = financials
            mock_rat.invoke.return_value = ratios
            return _run_fundamental_analysis_core(
                analysis_id="t027",
                company_name="TCS",
                ticker="TCS.NS",
            )

    def test_empty_financials_dict_no_crash(self) -> None:
        """Empty dict {} has no 'error' key -- agent must degrade gracefully."""
        result = self._run(financials={}, ratios=_RATIOS_MINIMAL)
        assert isinstance(result, FundamentalAnalysis)
        assert result.error is None

    def test_empty_financials_dict_score_at_minimum(self) -> None:
        """
        T-081: no financial data -> score is None with
        data_quality='insufficient', not a hard-floored 1.
        """
        result = self._run(financials={}, ratios={})
        assert result.score is None
        assert result.data_quality == "insufficient"

    def test_empty_ratios_dict_no_crash(self) -> None:
        result = self._run(financials=_FINANCIALS_MINIMAL, ratios={})
        assert isinstance(result, FundamentalAnalysis)

    def test_both_tools_empty_dict_no_crash(self) -> None:
        result = self._run(financials={}, ratios={})
        assert isinstance(result, FundamentalAnalysis)
        # T-081: both tools returning nothing -> insufficient data -> score
        # is None (not a numeric floor), and the model must still validate.
        assert result.score is None
        assert result.data_quality == "insufficient"

    def test_income_statement_empty_list(self) -> None:
        """income_statement present but empty -> no crash."""
        sparse: dict[str, Any] = {
            "income_statement": [],
            "balance_sheet": [],
            "cash_flow": [],
        }
        result = self._run(financials=sparse, ratios={})
        assert isinstance(result, FundamentalAnalysis)
        # T-081: insufficient data -> score is None, not a hard-floored 1.
        assert result.score is None
        assert result.data_quality == "insufficient"

    def test_single_year_income_no_cagr(self) -> None:
        """Only 1 fiscal year -> CAGR is None -> no crash."""
        single_year = {
            "income_statement": [
                {
                    "fiscal_year": "FY 2024",
                    "revenue_crores": 100_000.0,
                    "net_margin_pct": 15.0,
                }
            ],
            "balance_sheet": [],
            "cash_flow": [],
        }
        result = self._run(financials=single_year, ratios={})
        assert isinstance(result, FundamentalAnalysis)
        assert result.revenue_cagr_3y_pct is None

    def test_none_values_in_income_statement(self) -> None:
        """None values in income_statement fields must not crash scoring."""
        sparse = {
            "income_statement": [
                {
                    "fiscal_year": "FY 2024",
                    "revenue_crores": None,
                    "net_margin_pct": None,
                }
            ],
            "balance_sheet": [],
            "cash_flow": [],
        }
        result = self._run(financials=sparse, ratios={})
        assert isinstance(result, FundamentalAnalysis)

    def test_negative_free_cash_flow_handled(self) -> None:
        """Negative FCF must not crash the agent."""
        with_neg_fcf = {
            **_FINANCIALS_MINIMAL,
            "cash_flow": [
                {
                    "fiscal_year": "FY 2024",
                    "free_cash_flow_crores": -5_000.0,
                    "fcf_margin_pct": -2.1,
                    "operating_cash_flow_crores": 10_000.0,
                }
            ],
        }
        result = self._run(financials=with_neg_fcf, ratios=_RATIOS_MINIMAL)
        assert isinstance(result, FundamentalAnalysis)
        assert result.error is None

    def test_high_debt_to_equity_scores_low(self) -> None:
        """D/E > 2 should produce lower score than D/E = 0.02."""
        high_de_ratios = {**_RATIOS_MINIMAL, "debt_to_equity": 3.5}
        result_high = self._run(financials=_FINANCIALS_MINIMAL, ratios=high_de_ratios)
        result_low = self._run(financials=_FINANCIALS_MINIMAL, ratios=_RATIOS_MINIMAL)
        assert result_high.score is not None
        assert result_low.score is not None
        assert result_high.score <= result_low.score

    def test_missing_roe_in_ratios_no_crash(self) -> None:
        """ROE missing from ratios -> no crash, score still valid."""
        no_roe = {k: v for k, v in _RATIOS_MINIMAL.items() if k != "roe_pct"}
        result = self._run(financials=_FINANCIALS_MINIMAL, ratios=no_roe)
        assert isinstance(result, FundamentalAnalysis)
        assert result.score is not None
        assert 1 <= result.score <= 10

    def test_data_warnings_in_financials_no_crash(self) -> None:
        """data_warnings list in financials must not affect agent output."""
        with_warnings = {
            **_FINANCIALS_MINIMAL,
            "data_warnings": ["Alpha Vantage rate limit", "yFinance 429"],
        }
        result = self._run(financials=with_warnings, ratios=_RATIOS_MINIMAL)
        assert isinstance(result, FundamentalAnalysis)
        assert result.error is None


class TestTechnicalAnalystEmptyData:
    """Technical analyst with sparse OHLCV data must degrade gracefully."""

    def _run(
        self,
        price_data: dict[str, Any],
        llm_json: str = _TA_LLM_JSON,
    ) -> TechnicalAnalysis:
        from backend.agents.technical_analyst import _run_technical_analysis_core

        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=_make_llm(llm_json),
            ),
        ):
            mock_sp.invoke.return_value = price_data
            return _run_technical_analysis_core(
                analysis_id="t027",
                company_name="TCS",
                ticker="TCS.NS",
            )

    def test_empty_ohlcv_list_returns_error_model(self) -> None:
        """Empty ohlcv list -> error field set, no crash."""
        data = {**_PRICE_DATA_GOOD, "ohlcv": []}
        result = self._run(data)
        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_single_candle_all_indicators_none(self) -> None:
        """
        Single OHLCV candle: one close is enough for the agent to succeed
        (error=None), but all multi-close indicators must be None.
        RSI needs 15+, MA-50 needs 50, MA-200 needs 200 candles.
        """
        one_candle = [_OHLCV_260[0]]
        data = {**_PRICE_DATA_GOOD, "ohlcv": one_candle}
        result = self._run(data)
        assert isinstance(result, TechnicalAnalysis)
        # Agent succeeds -- one close is sufficient to set current_price
        assert result.error is None
        # All indicators requiring multiple closes must be None
        assert result.rsi_14 is None
        assert result.ma_50d is None
        assert result.ma_200d is None

    def test_fewer_than_50_candles_no_ma50(self) -> None:
        """With <50 candles, MA-50 must be None (not crash)."""
        forty_candles = _OHLCV_260[:40]
        data = {**_PRICE_DATA_GOOD, "ohlcv": forty_candles}
        result = self._run(data)
        # Either error (too few closes to compute key indicators) or
        # valid model with ma_50d=None
        assert isinstance(result, TechnicalAnalysis)
        if result.error is None:
            assert result.ma_50d is None

    def test_price_data_missing_stats_key(self) -> None:
        """price_data without 'stats' key must not crash agent."""
        data_no_stats = {
            "ticker": "TCS.NS",
            "ohlcv": _OHLCV_260,
            "data_points": 260,
        }
        result = self._run(data_no_stats)
        assert isinstance(result, TechnicalAnalysis)

    def test_ohlcv_with_zero_volume_no_crash(self) -> None:
        """Zero volume in all candles must not crash volume trend calc."""
        zero_vol = [{**c, "volume": 0} for c in _OHLCV_260]
        data = {**_PRICE_DATA_GOOD, "ohlcv": zero_vol}
        result = self._run(data)
        assert isinstance(result, TechnicalAnalysis)
        if result.error is None:
            assert result.volume_trend in (
                "increasing",
                "decreasing",
                "stable",
                "unknown",
            )

    def test_ohlcv_missing_close_key_returns_error(self) -> None:
        """OHLCV records without 'close' key -> error model."""
        no_close = [
            {"date": "2024-01-01", "open": 100.0, "volume": 1000} for _ in range(260)
        ]
        data = {**_PRICE_DATA_GOOD, "ohlcv": no_close}
        result = self._run(data)
        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_all_same_price_candles(self) -> None:
        """Flat price series (RSI=100) must not crash."""
        flat = [
            {
                "date": f"2024-01-{i:02d}",
                "open": 3000.0,
                "high": 3001.0,
                "low": 2999.0,
                "close": 3000.0,
                "volume": 1_000_000,
            }
            for i in range(1, 261)
        ]
        data = {**_PRICE_DATA_GOOD, "ohlcv": flat}
        result = self._run(data)
        assert isinstance(result, TechnicalAnalysis)
        if result.error is None:
            # Flat series -> RSI should be 100 (all gains, no losses)
            assert result.rsi_14 == pytest.approx(100.0)


class TestSentimentAnalystEmptyData:
    """Sentiment analyst with empty/minimal article data must degrade."""

    def _run(
        self,
        news_result: dict[str, Any],
        llm_json: str = _SA_LLM_JSON,
    ) -> SentimentAnalysis:
        from backend.agents.sentiment_analyst import _run_sentiment_analysis_core

        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm(llm_json),
            ),
        ):
            mock_news.invoke.return_value = news_result
            return _run_sentiment_analysis_core(
                analysis_id="t027",
                company_name="TCS",
                ticker="TCS.NS",
            )

    def test_zero_articles_returns_neutral_score(self) -> None:
        """Zero articles -> sentiment_score == 0.0 (neutral by convention)."""
        result = self._run({**_NEWS_RESULT_GOOD, "articles": []})
        assert result.sentiment_score == pytest.approx(0.0)
        assert result.articles_analysed == 0

    def test_zero_articles_no_red_flags(self) -> None:
        result = self._run({**_NEWS_RESULT_GOOD, "articles": []})
        assert result.red_flags == []
        assert result.red_flag_count == 0

    def test_empty_dict_no_articles_key(self) -> None:
        """News result without 'articles' key must not crash."""
        result = self._run({})
        assert isinstance(result, SentimentAnalysis)

    def test_articles_with_empty_title_and_description(self) -> None:
        """Articles with empty title/description strings must not crash."""
        empty_articles = [
            {"title": "", "description": "", "published_at": "2024-01-01"},
            {"title": None, "description": None, "published_at": "2024-01-01"},
        ]
        result = self._run({**_NEWS_RESULT_GOOD, "articles": empty_articles})
        assert isinstance(result, SentimentAnalysis)
        assert result.sentiment_score == pytest.approx(0.0)

    def test_single_article_no_crash(self) -> None:
        """Single article must work correctly."""
        single = [_NEWS_POSITIVE[0]]
        result = self._run({**_NEWS_RESULT_GOOD, "articles": single})
        assert isinstance(result, SentimentAnalysis)
        assert result.articles_analysed == 1

    def test_article_counts_sum_to_total(self) -> None:
        """positive + negative + neutral must equal articles_analysed."""
        result = self._run(_NEWS_RESULT_GOOD)
        assert (
            result.positive_articles
            + result.negative_articles
            + result.neutral_articles
        ) == result.articles_analysed

    def test_red_flag_count_matches_list_length(self) -> None:
        """red_flag_count must always equal len(red_flags)."""
        result = self._run(_NEWS_RESULT_GOOD)
        assert result.red_flag_count == len(result.red_flags)

    def test_articles_with_only_whitespace_titles(self) -> None:
        """Whitespace-only titles must score 0 and not crash."""
        ws_articles = [
            {"title": "   ", "description": "   ", "published_at": "2024-01-01"}
            for _ in range(5)
        ]
        result = self._run({**_NEWS_RESULT_GOOD, "articles": ws_articles})
        assert isinstance(result, SentimentAnalysis)

    def test_news_result_without_total_results_key(self) -> None:
        """total_results key being absent must not affect agent."""
        no_total = {k: v for k, v in _NEWS_RESULT_GOOD.items() if k != "total_results"}
        result = self._run(no_total)
        assert isinstance(result, SentimentAnalysis)


class TestMacroAnalystEmptyData:
    """Macro analyst with all-None data must degrade gracefully."""

    def _run(
        self,
        macro_result: dict[str, Any],
        company_name: str = "TCS",
        ticker: str = "TCS.NS",
        llm_json: str = _MA_LLM_JSON,
    ) -> MacroAnalysis:
        from backend.agents.macro_economist import _run_macro_analysis_core

        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm(llm_json),
            ),
        ):
            mock_macro.invoke.return_value = macro_result
            return _run_macro_analysis_core(
                analysis_id="t027",
                company_name=company_name,
                ticker=ticker,
            )

    def test_all_none_macro_data_no_crash(self) -> None:
        """All headline figures None -> agent must return valid model."""
        null_macro = {
            "repo_rate": None,
            "cpi_inflation": None,
            "gdp_growth": None,
            "warnings": ["All sources unavailable"],
            "cached": False,
        }
        result = self._run(null_macro)
        assert isinstance(result, MacroAnalysis)
        assert result.error is None

    def test_all_none_produces_valid_labels(self) -> None:
        null_macro: dict[str, Any] = {
            "repo_rate": None,
            "cpi_inflation": None,
            "gdp_growth": None,
            "warnings": [],
        }
        result = self._run(null_macro)
        assert result.macro_environment in ("favourable", "neutral", "unfavourable")
        assert result.sector_impact in ("tailwind", "neutral", "headwind")
        assert result.rate_stance in (
            "accommodative",
            "neutral",
            "calibrated_tightening",
            "tightening",
        )

    def test_empty_dict_no_crash(self) -> None:
        """Empty macro result {} must not crash."""
        result = self._run({})
        assert isinstance(result, MacroAnalysis)

    def test_repo_rate_none_stance_is_neutral(self) -> None:
        """None repo_rate -> _classify_rate_stance returns 'neutral'."""
        from backend.agents.macro_economist import _classify_rate_stance

        assert _classify_rate_stance(None) == "neutral"

    def test_cpi_none_inflation_trend_is_stable(self) -> None:
        """None CPI -> _classify_inflation_trend returns 'stable'."""
        from backend.agents.macro_economist import _classify_inflation_trend

        assert _classify_inflation_trend(None) == "stable"

    def test_repo_rate_none_direction_is_holding(self) -> None:
        """None repo_rate -> _classify_rate_direction returns 'holding'."""
        from backend.agents.macro_economist import _classify_rate_direction

        assert _classify_rate_direction(None) == "holding"

    def test_macro_environment_all_none_values(self) -> None:
        """None GDP, CPI, rate -> environment classification uses defaults."""
        from backend.agents.macro_economist import _classify_macro_environment

        result = _classify_macro_environment(None, None, None)
        assert result in ("favourable", "neutral", "unfavourable")

    def test_tailwinds_headwinds_with_none_cpi_gdp(self) -> None:
        """_build_tailwinds_headwinds with None inputs must return lists."""
        from backend.agents.macro_economist import _build_tailwinds_headwinds

        tw, hw = _build_tailwinds_headwinds("banking", "tightening", None, None)
        assert isinstance(tw, list)
        assert isinstance(hw, list)

    def test_unknown_sector_returns_diversified_impact(self) -> None:
        """Company with no matching sector keyword -> diversified sector."""
        result = self._run(_MACRO_RESULT_GOOD, company_name="XYZ Corp Unknown")
        assert isinstance(result, MacroAnalysis)
        assert result.sector_impact in ("tailwind", "neutral", "headwind")

    def test_warnings_list_in_macro_result_no_crash(self) -> None:
        """data warnings from the macro tool must not affect agent output."""
        with_warnings = {
            **_MACRO_RESULT_GOOD,
            "warnings": ["RBI scrape blocked (403)", "MOSPI CPI unavailable"],
        }
        result = self._run(with_warnings)
        assert isinstance(result, MacroAnalysis)
        assert result.error is None


# ---------------------------------------------------------------------------
# GAP 3: Error Paths (tool.invoke() RAISES, not returns error dict)
# ---------------------------------------------------------------------------


class TestFundamentalAnalystErrorPaths:
    """
    When tool.invoke() RAISES (not returns an error dict), the agent must
    catch the exception and return a valid model with error set.
    """

    def _run_with_raises(
        self,
        fin_exc: Exception | None = None,
        rat_exc: Exception | None = None,
    ) -> FundamentalAnalysis:
        from backend.agents.fundamental_analyst import _run_fundamental_analysis_core

        mock_fin = MagicMock()
        mock_rat = MagicMock()

        if fin_exc:
            mock_fin.invoke.side_effect = fin_exc
        else:
            mock_fin.invoke.return_value = _FINANCIALS_MINIMAL

        if rat_exc:
            mock_rat.invoke.side_effect = rat_exc
        else:
            mock_rat.invoke.return_value = _RATIOS_MINIMAL

        with (
            patch(
                "backend.agents.fundamental_analyst.fetch_financials",
                mock_fin,
            ),
            patch(
                "backend.agents.fundamental_analyst.fetch_ratios",
                mock_rat,
            ),
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=_make_llm(_FA_LLM_JSON),
            ),
        ):
            return _run_fundamental_analysis_core(
                analysis_id="t027",
                company_name="TCS",
                ticker="TCS.NS",
            )

    def test_fetch_financials_raises_returns_valid_model(self) -> None:
        result = self._run_with_raises(fin_exc=ConnectionError("timeout"))
        assert isinstance(result, FundamentalAnalysis)
        # Exception path -> financials set to empty, agent continues
        assert result.error is None or isinstance(result.error, str)

    def test_fetch_ratios_raises_returns_valid_model(self) -> None:
        result = self._run_with_raises(rat_exc=RuntimeError("500 error"))
        assert isinstance(result, FundamentalAnalysis)

    def test_both_tools_raise_returns_valid_model(self) -> None:
        result = self._run_with_raises(
            fin_exc=ConnectionError("network"),
            rat_exc=RuntimeError("server error"),
        )
        assert isinstance(result, FundamentalAnalysis)
        # T-081: both tools failing -> no financial data at all -> score is
        # None with data_quality='insufficient', not a hard-floored 1.
        assert result.score is None
        assert result.data_quality == "insufficient"

    def test_node_never_raises_on_core_exception(self) -> None:
        """The LangGraph node must never propagate an exception."""
        from backend.agents.fundamental_analyst import run_fundamental_analysis

        with patch(
            "backend.agents.fundamental_analyst._run_fundamental_analysis_core",
            side_effect=RuntimeError("Unexpected core failure"),
        ):
            result = run_fundamental_analysis(
                {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
            )
        assert "fundamental" in result
        assert result["fundamental"]["error"] is not None


class TestTechnicalAnalystErrorPaths:
    """When fetch_stock_price RAISES the agent must handle it gracefully."""

    def test_fetch_stock_price_raises_returns_error_model(self) -> None:
        from backend.agents.technical_analyst import _run_technical_analysis_core

        mock_sp = MagicMock()
        mock_sp.invoke.side_effect = ConnectionError("Yahoo timeout")

        with (
            patch(
                "backend.agents.technical_analyst.fetch_stock_price",
                mock_sp,
            ),
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=_make_llm(_TA_LLM_JSON),
            ),
        ):
            result = _run_technical_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_fetch_stock_price_returns_error_dict(self) -> None:
        from backend.agents.technical_analyst import _run_technical_analysis_core

        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=_make_llm(_TA_LLM_JSON),
            ),
        ):
            mock_sp.invoke.return_value = {
                "error": "ticker_not_found",
                "message": "No data for TCS.NS",
            }
            result = _run_technical_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, TechnicalAnalysis)
        assert result.error is not None

    def test_node_never_raises_on_core_exception(self) -> None:
        from backend.agents.technical_analyst import run_technical_analysis

        with patch(
            "backend.agents.technical_analyst._run_technical_analysis_core",
            side_effect=RuntimeError("Unexpected failure"),
        ):
            result = run_technical_analysis(
                {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
            )
        assert "technical" in result
        assert result["technical"]["error"] is not None

    def test_llm_raises_uses_fallback_summary(self) -> None:
        from backend.agents.technical_analyst import _run_technical_analysis_core

        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as mock_sp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=_make_llm_raises(RuntimeError("LLM down")),
            ),
        ):
            mock_sp.invoke.return_value = _PRICE_DATA_GOOD
            result = _run_technical_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, TechnicalAnalysis)
        assert result.error is None
        assert len(result.summary) > 0


class TestSentimentAnalystErrorPaths:
    """Error paths for News Sentiment Agent."""

    def test_fetch_news_raises_returns_error_model(self) -> None:
        from backend.agents.sentiment_analyst import _run_sentiment_analysis_core

        mock_news = MagicMock()
        mock_news.invoke.side_effect = ConnectionError("NewsAPI down")

        with (
            patch(
                "backend.agents.sentiment_analyst.fetch_news",
                mock_news,
            ),
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm(_SA_LLM_JSON),
            ),
        ):
            result = _run_sentiment_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, SentimentAnalysis)
        assert result.error is not None

    def test_fetch_news_returns_error_dict(self) -> None:
        from backend.agents.sentiment_analyst import _run_sentiment_analysis_core

        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm(_SA_LLM_JSON),
            ),
        ):
            mock_news.invoke.return_value = {
                "error": "api_limit",
                "message": "100 req/day exceeded",
            }
            result = _run_sentiment_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, SentimentAnalysis)
        assert result.error is not None

    def test_chroma_raises_is_non_fatal(self) -> None:
        """ChromaDB failure must not cause error field to be set."""
        from backend.agents.sentiment_analyst import _run_sentiment_analysis_core

        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                side_effect=RuntimeError("ChromaDB unavailable"),
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm(_SA_LLM_JSON),
            ),
        ):
            mock_news.invoke.return_value = _NEWS_RESULT_GOOD
            result = _run_sentiment_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, SentimentAnalysis)
        assert result.error is None

    def test_llm_returns_invalid_json_uses_fallback(self) -> None:
        from backend.agents.sentiment_analyst import _run_sentiment_analysis_core

        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mock_news,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm("not valid JSON at all"),
            ),
        ):
            mock_news.invoke.return_value = _NEWS_RESULT_GOOD
            result = _run_sentiment_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, SentimentAnalysis)
        assert result.error is None
        assert len(result.summary) > 0

    def test_node_never_raises_on_core_exception(self) -> None:
        from backend.agents.sentiment_analyst import run_sentiment_analysis

        with patch(
            "backend.agents.sentiment_analyst._run_sentiment_analysis_core",
            side_effect=RuntimeError("Unexpected failure"),
        ):
            result = run_sentiment_analysis(
                {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
            )
        assert "sentiment" in result
        assert result["sentiment"]["error"] is not None


class TestMacroAnalystErrorPaths:
    """Error paths for Macro Economist Agent."""

    def test_fetch_macro_raises_returns_error_model(self) -> None:
        from backend.agents.macro_economist import _run_macro_analysis_core

        mock_macro = MagicMock()
        mock_macro.invoke.side_effect = ConnectionError("RBI scraper blocked")

        with (
            patch(
                "backend.agents.macro_economist.fetch_macro_data",
                mock_macro,
            ),
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm(_MA_LLM_JSON),
            ),
        ):
            result = _run_macro_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, MacroAnalysis)
        assert result.error is not None

    def test_fetch_macro_returns_error_dict(self) -> None:
        from backend.agents.macro_economist import _run_macro_analysis_core

        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm(_MA_LLM_JSON),
            ),
        ):
            mock_macro.invoke.return_value = {
                "error": "scrape_blocked",
                "message": "403 Forbidden",
            }
            result = _run_macro_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, MacroAnalysis)
        assert result.error is not None

    def test_chroma_raises_is_non_fatal(self) -> None:
        from backend.agents.macro_economist import _run_macro_analysis_core

        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                side_effect=RuntimeError("ChromaDB timeout"),
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm(_MA_LLM_JSON),
            ),
        ):
            mock_macro.invoke.return_value = _MACRO_RESULT_GOOD
            result = _run_macro_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, MacroAnalysis)
        assert result.error is None

    def test_llm_raises_uses_fallback_summary(self) -> None:
        from backend.agents.macro_economist import _run_macro_analysis_core

        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm_raises(RuntimeError("Groq timeout")),
            ),
        ):
            mock_macro.invoke.return_value = _MACRO_RESULT_GOOD
            result = _run_macro_analysis_core("t027", "TCS", "TCS.NS")

        assert isinstance(result, MacroAnalysis)
        assert result.error is None
        assert len(result.summary) > 0

    def test_node_never_raises_on_core_exception(self) -> None:
        from backend.agents.macro_economist import run_macro_analysis

        with patch(
            "backend.agents.macro_economist._run_macro_analysis_core",
            side_effect=RuntimeError("Unexpected failure"),
        ):
            result = run_macro_analysis(
                {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
            )
        assert "macro" in result
        assert result["macro"]["error"] is not None


# ---------------------------------------------------------------------------
# GAP 4: Cross-agent state dict / JSON-safe contract
# ---------------------------------------------------------------------------


class TestAllAgentsNodeContract:
    """
    Every agent node must:
    1. Return a dict with the correct state key
    2. Produce a JSON-safe output (datetime serialised via mode='json')
    3. Include required base fields (agent_name, analysis_id, ticker)
    4. Handle empty ticker gracefully (return error, not crash)
    """

    # --- Fundamental ---

    def _fa_invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from backend.agents.fundamental_analyst import run_fundamental_analysis

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mf,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mr,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=_make_llm(_FA_LLM_JSON),
            ),
        ):
            mf.invoke.return_value = _FINANCIALS_MINIMAL
            mr.invoke.return_value = _RATIOS_MINIMAL
            return cast(dict[str, Any], run_fundamental_analysis(state))

    def test_fa_returns_fundamental_key(self) -> None:
        result = self._fa_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        assert "fundamental" in result

    def test_fa_output_json_safe(self) -> None:
        result = self._fa_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        obj = FundamentalAnalysis(**result["fundamental"])
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_fa_empty_ticker_returns_error(self) -> None:
        result = self._fa_invoke({"job_id": "x", "company_name": "TCS", "ticker": ""})
        assert result["fundamental"]["error"] is not None

    def test_fa_required_base_fields_present(self) -> None:
        result = self._fa_invoke(
            {"job_id": "job-123", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        d = result["fundamental"]
        assert d["agent_name"] == "fundamental_analyst"
        assert d["analysis_id"] == "job-123"
        assert d["ticker"] == "TCS.NS"

    # --- Technical ---

    def _ta_invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from backend.agents.technical_analyst import run_technical_analysis

        with (
            patch("backend.agents.technical_analyst.fetch_stock_price") as msp,
            patch(
                "backend.agents.technical_analyst.get_llm",
                return_value=_make_llm(_TA_LLM_JSON),
            ),
        ):
            msp.invoke.return_value = _PRICE_DATA_GOOD
            return cast(dict[str, Any], run_technical_analysis(state))

    def test_ta_returns_technical_key(self) -> None:
        result = self._ta_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        assert "technical" in result

    def test_ta_output_json_safe(self) -> None:
        result = self._ta_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        obj = TechnicalAnalysis(**result["technical"])
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_ta_empty_ticker_returns_error(self) -> None:
        result = self._ta_invoke({"job_id": "x", "company_name": "TCS", "ticker": ""})
        assert result["technical"]["error"] is not None

    def test_ta_required_base_fields_present(self) -> None:
        result = self._ta_invoke(
            {"job_id": "job-456", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        d = result["technical"]
        assert d["agent_name"] == "technical_analyst"
        assert d["analysis_id"] == "job-456"

    # --- Sentiment ---

    def _sa_invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from backend.agents.sentiment_analyst import run_sentiment_analysis

        with (
            patch("backend.agents.sentiment_analyst.fetch_news") as mn,
            patch(
                "backend.agents.sentiment_analyst.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.sentiment_analyst.get_llm",
                return_value=_make_llm(_SA_LLM_JSON),
            ),
        ):
            mn.invoke.return_value = _NEWS_RESULT_GOOD
            return cast(dict[str, Any], run_sentiment_analysis(state))

    def test_sa_returns_sentiment_key(self) -> None:
        result = self._sa_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        assert "sentiment" in result

    def test_sa_output_json_safe(self) -> None:
        result = self._sa_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        obj = SentimentAnalysis(**result["sentiment"])
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_sa_empty_ticker_returns_error(self) -> None:
        result = self._sa_invoke({"job_id": "x", "company_name": "TCS", "ticker": ""})
        assert result["sentiment"]["error"] is not None

    def test_sa_required_base_fields_present(self) -> None:
        result = self._sa_invoke(
            {"job_id": "job-789", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        d = result["sentiment"]
        assert d["agent_name"] == "news_sentiment"
        assert d["analysis_id"] == "job-789"

    # --- Macro ---

    def _ma_invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from backend.agents.macro_economist import run_macro_analysis

        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mm,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=_make_llm(_MA_LLM_JSON),
            ),
        ):
            mm.invoke.return_value = _MACRO_RESULT_GOOD
            return cast(dict[str, Any], run_macro_analysis(state))

    def test_ma_returns_macro_key(self) -> None:
        result = self._ma_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        assert "macro" in result

    def test_ma_output_json_safe(self) -> None:
        result = self._ma_invoke(
            {"job_id": "x", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        obj = MacroAnalysis(**result["macro"])
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_ma_empty_ticker_returns_error(self) -> None:
        result = self._ma_invoke({"job_id": "x", "company_name": "TCS", "ticker": ""})
        assert result["macro"]["error"] is not None

    def test_ma_required_base_fields_present(self) -> None:
        result = self._ma_invoke(
            {"job_id": "job-999", "company_name": "TCS", "ticker": "TCS.NS"}
        )
        d = result["macro"]
        assert d["agent_name"] == "macro_economist"
        assert d["analysis_id"] == "job-999"


# ---------------------------------------------------------------------------
# GAP 5: Tracing integration — @traced_agent __wrapped__ check
# ---------------------------------------------------------------------------


class TestAllAgentsTracingIntegration:
    """
    Verify that @traced_agent was applied to all four node functions.
    @traced_agent uses functools.wraps, which sets __wrapped__ on the
    decorated function.  This is the structural proof the decorator ran.
    """

    def test_fundamental_analyst_node_is_traced(self) -> None:
        from backend.agents.fundamental_analyst import run_fundamental_analysis

        assert hasattr(run_fundamental_analysis, "__wrapped__"), (
            "run_fundamental_analysis is missing __wrapped__; "
            "@traced_agent was not applied"
        )

    def test_technical_analyst_node_is_traced(self) -> None:
        from backend.agents.technical_analyst import run_technical_analysis

        assert hasattr(run_technical_analysis, "__wrapped__")

    def test_sentiment_analyst_node_is_traced(self) -> None:
        from backend.agents.sentiment_analyst import run_sentiment_analysis

        assert hasattr(run_sentiment_analysis, "__wrapped__")

    def test_macro_economist_node_is_traced(self) -> None:
        from backend.agents.macro_economist import run_macro_analysis

        assert hasattr(run_macro_analysis, "__wrapped__")

    def test_all_node_names_preserved(self) -> None:
        """functools.wraps must preserve __name__ on all four nodes."""
        from backend.agents.fundamental_analyst import run_fundamental_analysis
        from backend.agents.macro_economist import run_macro_analysis
        from backend.agents.sentiment_analyst import run_sentiment_analysis
        from backend.agents.technical_analyst import run_technical_analysis

        assert run_fundamental_analysis.__name__ == "run_fundamental_analysis"
        assert run_technical_analysis.__name__ == "run_technical_analysis"
        assert run_sentiment_analysis.__name__ == "run_sentiment_analysis"
        assert run_macro_analysis.__name__ == "run_macro_analysis"
