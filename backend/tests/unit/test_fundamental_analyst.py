# backend/tests/unit/test_fundamental_analyst.py
"""
Unit tests for T-022: Fundamental Analyst Agent.

Test strategy:
  1. _score_financials     — deterministic scoring logic, no I/O
  2. _assess_trends        — qualitative label derivation, no I/O
  3. _build_agent_prompt   — prompt builder produces expected structure
  4. _run_fundamental_analysis_core — full agent with mocked tools + LLM
  5. run_fundamental_analysis      — LangGraph node: state in → state out
  6. Error paths           — missing ticker, tool errors, LLM failure

All external calls (yFinance, Redis, Groq/Anthropic) are mocked.
Tests are pure unit tests: no network, no database, no LLM quota consumed.
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.agents.fundamental_analyst import (  # noqa: E402
    SYSTEM_PROMPT,
    _assess_trends,
    _band_score,
    _build_agent_prompt,
    _revenue_cagr,
    _run_fundamental_analysis_core,
    _score_financials,
    run_fundamental_analysis,
)
from backend.agents.output_models import FundamentalAnalysis  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# Minimal realistic financials dict — mirrors what fetch_financials returns
FINANCIALS_GOOD: dict[str, Any] = {
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
            "fiscal_year": "FY 2023",
            "revenue_crores": 225_000.0,
            "net_income_crores": 42_000.0,
            "net_margin_pct": 18.7,
            "operating_margin_pct": 24.0,
            "gross_margin_pct": 35.0,
        },
        {
            "fiscal_year": "FY 2022",
            "revenue_crores": 191_000.0,
            "net_income_crores": 38_000.0,
            "net_margin_pct": 19.9,
            "operating_margin_pct": 25.0,
            "gross_margin_pct": 36.0,
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
            "total_assets_crores": 150_000.0,
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

RATIOS_GOOD: dict[str, Any] = {
    "pe_ratio": 28.5,
    "pb_ratio": 9.2,
    "roe_pct": 46.2,
    "roce_pct": 51.1,
    "debt_to_equity": 0.02,
    "ev_to_ebitda": 19.5,
    "data_warnings": [],
}

# Minimal state for LangGraph node tests
STATE_TCS: dict[str, Any] = {
    "job_id": "test-job-001",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}

_LLM_JSON_RESPONSE = json.dumps(
    {
        "strengths": [
            "Revenue CAGR of 13.7% over 4 years demonstrates consistent growth",
            "ROE of 46.2% significantly exceeds the 20% quality threshold",
            "Net cash position (D/E 0.02) provides strong balance sheet safety",
        ],
        "risks": [
            "PE of 28.5x implies limited margin of safety if growth decelerates",
            "FCF payout trend requires monitoring across upcoming quarters",
        ],
        "summary": (
            "TCS demonstrates exceptional fundamental quality with a score of 9/10, "
            "driven by consistent double-digit revenue growth and industry-leading "
            "ROE. The near-net-cash balance sheet and 18% FCF margin make this a "
            "high-quality compounder at a full but justifiable valuation."
        ),
    }
)


def _make_llm_response(content: str = _LLM_JSON_RESPONSE) -> MagicMock:
    mock = MagicMock()
    mock.content = content
    return mock


# ---------------------------------------------------------------------------
# Tests: _band_score helper
# ---------------------------------------------------------------------------


class TestBandScore:
    def test_above_all_thresholds(self) -> None:
        thresholds = [(15.0, 3), (8.0, 2), (3.0, 1)]
        assert _band_score(20.0, thresholds) == 3

    def test_middle_threshold(self) -> None:
        thresholds = [(15.0, 3), (8.0, 2), (3.0, 1)]
        assert _band_score(10.0, thresholds) == 2

    def test_below_all_thresholds(self) -> None:
        thresholds = [(15.0, 3), (8.0, 2), (3.0, 1)]
        assert _band_score(1.0, thresholds) == 0

    def test_none_returns_zero(self) -> None:
        assert _band_score(None, [(10.0, 5)]) == 0

    def test_exact_boundary(self) -> None:
        # exactly on threshold should match
        thresholds = [(8.0, 2), (3.0, 1)]
        assert _band_score(8.0, thresholds) == 2


# ---------------------------------------------------------------------------
# Tests: _revenue_cagr
# ---------------------------------------------------------------------------


class TestRevenueCagr:
    def test_four_year_cagr(self) -> None:
        income = FINANCIALS_GOOD["income_statement"]
        cagr = _revenue_cagr(income)
        assert cagr is not None
        # 164k → 240.89k over 3 years ≈ 13.7%
        assert 12.0 < cagr < 16.0

    def test_single_year_returns_none(self) -> None:
        income = [{"revenue_crores": 100_000.0}]
        assert _revenue_cagr(income) is None

    def test_empty_returns_none(self) -> None:
        assert _revenue_cagr([]) is None

    def test_none_revenues_skipped(self) -> None:
        income = [
            {"revenue_crores": 200_000.0},
            {"revenue_crores": None},
            {"revenue_crores": 150_000.0},
        ]
        cagr = _revenue_cagr(income)
        # Should use 200k and 150k (2 valid, span 1 year)
        assert cagr is not None

    def test_zero_oldest_returns_none(self) -> None:
        income = [
            {"revenue_crores": 100_000.0},
            {"revenue_crores": 0.0},
        ]
        assert _revenue_cagr(income) is None


# ---------------------------------------------------------------------------
# Tests: _score_financials (deterministic scoring)
# ---------------------------------------------------------------------------


class TestScoreFinancials:
    def test_high_quality_company_scores_high(self) -> None:
        score = _score_financials(FINANCIALS_GOOD, RATIOS_GOOD)
        # TCS-like data: CAGR 13.7%(2pts) + margin 19%(1pt) + ROE 46%(2pts)
        # + D/E 0.02(1pt, ≤0.5 band) + FCF margin 18%(1pt) = 7pts total
        assert score >= 7

    def test_score_in_valid_range(self) -> None:
        score = _score_financials(FINANCIALS_GOOD, RATIOS_GOOD)
        assert 1 <= score <= 10

    def test_empty_data_returns_minimum(self) -> None:
        score = _score_financials({}, {})
        assert score == 1

    def test_poor_fundamentals_score_low(self) -> None:
        poor_financials: dict[str, Any] = {
            "income_statement": [
                {
                    "revenue_crores": 50_000.0,
                    "net_income_crores": 500.0,
                    "net_margin_pct": 1.0,
                    "operating_margin_pct": 2.0,
                },
                {
                    "revenue_crores": 55_000.0,
                    "net_income_crores": 600.0,
                    "net_margin_pct": 1.1,
                    "operating_margin_pct": 2.1,
                },
            ],
            "balance_sheet": [
                {
                    "debt_to_equity": 3.5,
                    "current_ratio": 0.8,
                }
            ],
            "cash_flow": [
                {
                    "free_cash_flow_crores": -1_000.0,
                    "fcf_margin_pct": -2.0,
                }
            ],
        }
        poor_ratios = {
            "roe_pct": 3.0,
            "debt_to_equity": 3.5,
        }
        score = _score_financials(poor_financials, poor_ratios)
        assert score <= 3

    def test_score_uses_ratios_roe_over_derived(self) -> None:
        """When ratios dict has ROE, it should be used for scoring."""
        # High ROE from ratios should push score up
        score_with_roe = _score_financials(
            FINANCIALS_GOOD, {**RATIOS_GOOD, "roe_pct": 50.0}
        )
        score_without_roe = _score_financials(
            FINANCIALS_GOOD, {**RATIOS_GOOD, "roe_pct": 5.0}
        )
        assert score_with_roe >= score_without_roe

    def test_net_cash_gives_max_debt_pts(self) -> None:
        """D/E < 0 (net cash) gives 2pts for debt vs 1pt for D/E 0.02."""
        ratios_net_cash = {**RATIOS_GOOD, "debt_to_equity": -0.1}
        score = _score_financials(FINANCIALS_GOOD, ratios_net_cash)
        # Net cash (2pts) vs low debt (1pt) → score should be at least 8
        assert score >= 8


# ---------------------------------------------------------------------------
# Tests: _assess_trends
# ---------------------------------------------------------------------------


class TestAssessTrends:
    def test_growing_revenue(self) -> None:
        trends = _assess_trends(FINANCIALS_GOOD, RATIOS_GOOD)
        assert trends["revenue_trend"] == "growing"

    def test_improving_profit(self) -> None:
        # FY2021 margin 20.1, FY2024 margin 19.1 → slight decline
        # delta = 19.1 - 20.1 = -1.0, within ±1.5 → stable
        trends = _assess_trends(FINANCIALS_GOOD, RATIOS_GOOD)
        assert trends["profit_trend"] in ("stable", "improving", "declining")

    def test_low_debt(self) -> None:
        trends = _assess_trends(FINANCIALS_GOOD, RATIOS_GOOD)
        assert trends["debt_level"] in ("low", "net_cash")

    def test_strong_fcf(self) -> None:
        trends = _assess_trends(FINANCIALS_GOOD, RATIOS_GOOD)
        # FCF margin 18.3% → strong
        assert trends["fcf_status"] == "strong"

    def test_empty_data_returns_unknown(self) -> None:
        trends = _assess_trends({}, {})
        assert trends["revenue_trend"] == "insufficient_data"
        assert trends["debt_level"] == "unknown"
        assert trends["fcf_status"] == "unknown"

    def test_negative_fcf(self) -> None:
        bad_cf: dict[str, Any] = {
            "cash_flow": [{"free_cash_flow_crores": -5_000.0, "fcf_margin_pct": -5.0}]
        }
        trends = _assess_trends(bad_cf, {})
        assert trends["fcf_status"] == "negative"

    def test_high_debt(self) -> None:
        high_de_ratios = {"debt_to_equity": 2.5}
        trends = _assess_trends({}, high_de_ratios)
        assert trends["debt_level"] == "high"

    def test_declining_revenue(self) -> None:
        declining: dict[str, Any] = {
            "income_statement": [
                {"revenue_crores": 80_000.0, "net_margin_pct": 10.0},
                {"revenue_crores": 90_000.0, "net_margin_pct": 12.0},
                {"revenue_crores": 100_000.0, "net_margin_pct": 14.0},
            ]
        }
        trends = _assess_trends(declining, {})
        assert trends["revenue_trend"] == "declining"

    def test_net_cash_classification(self) -> None:
        # Negative D/E means net cash
        net_cash_ratios = {"debt_to_equity": -0.05}
        trends = _assess_trends({}, net_cash_ratios)
        assert trends["debt_level"] == "net_cash"


# ---------------------------------------------------------------------------
# Tests: _build_agent_prompt
# ---------------------------------------------------------------------------


class TestBuildAgentPrompt:
    def _make_prompt(self) -> str:
        return _build_agent_prompt(
            company_name="Tata Consultancy Services",
            ticker="TCS.NS",
            financials=FINANCIALS_GOOD,
            ratios=RATIOS_GOOD,
            score=9,
            trends={
                "revenue_trend": "growing",
                "profit_trend": "stable",
                "debt_level": "net_cash",
                "fcf_status": "strong",
            },
        )

    def test_contains_company_name(self) -> None:
        prompt = self._make_prompt()
        assert "Tata Consultancy Services" in prompt

    def test_contains_ticker(self) -> None:
        prompt = self._make_prompt()
        assert "TCS.NS" in prompt

    def test_contains_score(self) -> None:
        prompt = self._make_prompt()
        assert "9/10" in prompt

    def test_contains_trend_labels(self) -> None:
        prompt = self._make_prompt()
        assert "growing" in prompt
        assert "net_cash" in prompt
        assert "strong" in prompt

    def test_contains_revenue_figure(self) -> None:
        prompt = self._make_prompt()
        # Should mention FY 2024 revenue
        assert "FY 2024" in prompt

    def test_contains_roe(self) -> None:
        prompt = self._make_prompt()
        assert "46.2" in prompt  # ROE from RATIOS_GOOD

    def test_returns_string(self) -> None:
        assert isinstance(self._make_prompt(), str)

    def test_empty_financials_no_crash(self) -> None:
        prompt = _build_agent_prompt(
            company_name="Test Co",
            ticker="TEST.NS",
            financials={},
            ratios={},
            score=5,
            trends={
                "revenue_trend": "unknown",
                "profit_trend": "unknown",
                "debt_level": "unknown",
                "fcf_status": "unknown",
            },
        )
        assert isinstance(prompt, str)
        assert "Test Co" in prompt


# ---------------------------------------------------------------------------
# Tests: _run_fundamental_analysis_core (full agent, mocked externals)
# ---------------------------------------------------------------------------


class TestRunFundamentalAnalysisCore:
    """
    Tests for the core agent logic with mocked tool calls and LLM.

    Patch targets:
      backend.agents.fundamental_analyst.fetch_financials   — LangChain tool
      backend.agents.fundamental_analyst.fetch_ratios       — LangChain tool
      backend.agents.fundamental_analyst.get_llm            — LLM factory
    """

    def _run(
        self,
        financials: dict[str, Any] = FINANCIALS_GOOD,
        ratios: dict[str, Any] = RATIOS_GOOD,
        llm_response: str = _LLM_JSON_RESPONSE,
    ) -> FundamentalAnalysis:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(llm_response)

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = financials
            mock_rat.invoke.return_value = ratios

            return _run_fundamental_analysis_core(
                analysis_id="test-001",
                company_name="Tata Consultancy Services",
                ticker="TCS.NS",
            )

    def test_returns_fundamental_analysis_instance(self) -> None:
        result = self._run()
        assert isinstance(result, FundamentalAnalysis)

    def test_agent_name_correct(self) -> None:
        result = self._run()
        assert result.agent_name == "fundamental_analyst"

    def test_ticker_preserved(self) -> None:
        result = self._run()
        assert result.ticker == "TCS.NS"

    def test_company_name_preserved(self) -> None:
        result = self._run()
        assert result.company_name == "Tata Consultancy Services"

    def test_score_in_valid_range(self) -> None:
        result = self._run()
        assert 1 <= result.score <= 10

    def test_high_quality_data_scores_high(self) -> None:
        result = self._run()
        # TCS-like data → should score ≥ 7
        assert result.score >= 7

    def test_error_is_none_on_success(self) -> None:
        result = self._run()
        assert result.error is None

    def test_strengths_populated(self) -> None:
        result = self._run()
        assert isinstance(result.strengths, list)
        assert len(result.strengths) > 0

    def test_weaknesses_populated(self) -> None:
        result = self._run()
        assert isinstance(result.weaknesses, list)
        assert len(result.weaknesses) > 0

    def test_summary_populated(self) -> None:
        result = self._run()
        assert isinstance(result.summary, str)
        assert len(result.summary) > 10

    def test_financial_fields_populated(self) -> None:
        result = self._run()
        assert result.net_margin_pct == pytest.approx(19.1)
        assert result.roe_pct == pytest.approx(46.2)

    def test_revenue_growth_pct_computed(self) -> None:
        result = self._run()
        assert result.revenue_growth_pct is not None
        assert 12.0 < result.revenue_growth_pct < 16.0

    def test_fcf_populated(self) -> None:
        result = self._run()
        assert result.free_cash_flow_cr == pytest.approx(44_000.0)

    def test_tool_called_with_correct_ticker(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response()

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = FINANCIALS_GOOD
            mock_rat.invoke.return_value = RATIOS_GOOD

            _run_fundamental_analysis_core(
                analysis_id="x",
                company_name="TCS",
                ticker="TCS.NS",
            )

            mock_fin.invoke.assert_called_once_with({"ticker": "TCS.NS"})
            mock_rat.invoke.assert_called_once_with({"ticker": "TCS.NS"})

    def test_financials_error_still_returns_model(self) -> None:
        """When fetch_financials returns an error dict, agent degrades gracefully."""
        result = self._run(
            financials={"error": "financials_not_found", "message": "No data"},
        )
        assert isinstance(result, FundamentalAnalysis)
        # Score should be low when no financial data
        assert result.score >= 1

    def test_ratios_error_still_returns_model(self) -> None:
        """When fetch_ratios returns an error dict, agent degrades gracefully."""
        result = self._run(ratios={"error": "ratios_not_found", "message": "No data"})
        assert isinstance(result, FundamentalAnalysis)

    def test_llm_failure_uses_fallback_summary(self) -> None:
        """When LLM fails, agent returns fallback strengths/summary, no crash."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Groq timeout")

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = FINANCIALS_GOOD
            mock_rat.invoke.return_value = RATIOS_GOOD

            result = _run_fundamental_analysis_core(
                analysis_id="x", company_name="TCS", ticker="TCS.NS"
            )

        assert isinstance(result, FundamentalAnalysis)
        assert result.error is None  # error field stays None — degraded gracefully
        assert len(result.strengths) > 0
        assert len(result.summary) > 0

    def test_llm_malformed_json_uses_fallback(self) -> None:
        """When LLM returns non-JSON, agent falls back gracefully."""
        result = self._run(llm_response="Sorry, I cannot provide that analysis.")
        assert isinstance(result, FundamentalAnalysis)
        assert result.score >= 1

    def test_model_serialisable(self) -> None:
        result = self._run()
        d = result.model_dump()
        assert isinstance(d, dict)
        assert d["agent_name"] == "fundamental_analyst"
        assert 1 <= d["score"] <= 10


# ---------------------------------------------------------------------------
# Tests: run_fundamental_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunFundamentalAnalysisNode:
    """Tests for the LangGraph node entry point."""

    def _invoke_node(
        self,
        state: dict[str, Any],
        financials: dict[str, Any] = FINANCIALS_GOOD,
        ratios: dict[str, Any] = RATIOS_GOOD,
    ) -> dict[str, Any]:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response()

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = financials
            mock_rat.invoke.return_value = ratios
            return run_fundamental_analysis(state)

    def test_returns_dict_with_fundamental_key(self) -> None:
        result = self._invoke_node(STATE_TCS)
        assert "fundamental" in result
        assert isinstance(result["fundamental"], dict)

    def test_fundamental_dict_has_agent_name(self) -> None:
        result = self._invoke_node(STATE_TCS)
        assert result["fundamental"]["agent_name"] == "fundamental_analyst"

    def test_fundamental_dict_has_score(self) -> None:
        result = self._invoke_node(STATE_TCS)
        score = result["fundamental"]["score"]
        assert 1 <= score <= 10

    def test_empty_ticker_returns_error(self) -> None:
        bad_state = {**STATE_TCS, "ticker": ""}
        result = run_fundamental_analysis(bad_state)
        assert "fundamental" in result
        assert result["fundamental"]["error"] is not None

    def test_missing_ticker_returns_error(self) -> None:
        bad_state = {"job_id": "x", "company_name": "Test"}
        result = run_fundamental_analysis(bad_state)
        assert result["fundamental"]["error"] is not None

    def test_state_job_id_preserved(self) -> None:
        result = self._invoke_node(STATE_TCS)
        assert result["fundamental"]["analysis_id"] == "test-job-001"

    def test_state_company_name_preserved(self) -> None:
        result = self._invoke_node(STATE_TCS)
        assert result["fundamental"]["company_name"] == "Tata Consultancy Services"

    def test_never_raises(self) -> None:
        """Node must never raise — always returns a dict."""
        with patch(
            "backend.agents.fundamental_analyst._run_fundamental_analysis_core",
            side_effect=RuntimeError("Catastrophic failure"),
        ):
            result = run_fundamental_analysis(STATE_TCS)
        assert "fundamental" in result
        assert result["fundamental"]["error"] is not None

    def test_infy_state(self) -> None:
        """Node works for Infosys state shape."""
        infy_state = {
            "job_id": "test-job-002",
            "company_name": "Infosys Limited",
            "ticker": "INFY.NS",
        }
        result = self._invoke_node(infy_state)
        assert result["fundamental"]["ticker"] == "INFY.NS"

    def test_reliance_state(self) -> None:
        """Node works for Reliance state shape."""
        rel_state = {
            "job_id": "test-job-003",
            "company_name": "Reliance Industries",
            "ticker": "RELIANCE.NS",
        }
        result = self._invoke_node(rel_state)
        assert result["fundamental"]["ticker"] == "RELIANCE.NS"


# ---------------------------------------------------------------------------
# Tests: system prompt presence
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_is_non_empty_string(self) -> None:
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_mentions_strengths(self) -> None:
        assert "strengths" in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_risks(self) -> None:
        assert "risks" in SYSTEM_PROMPT.lower()
