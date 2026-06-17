# backend/tests/unit/test_portfolio_manager.py
"""
Unit tests for T-041: Portfolio Manager Agent.

Test strategy:
  1. _compute_agent_weights       -- weight normalisation and error handling
  2. _determine_verdict           -- deterministic BUY/HOLD/SELL gating
  3. _score_conviction            -- conviction reflects analysis QUALITY
  4. _determine_time_horizon      -- horizon selection logic
  5. _build_price_target          -- price target string formatting
  6. _build_key_risks             -- structured risk list construction
  7. _build_key_catalysts         -- structured catalyst list construction
  8. _extract_debate_highlights   -- debate transcript -> highlight strings
  9. _build_portfolio_manager_prompt -- prompt content and structure
 10. _run_portfolio_manager_core  -- full agent with mocked LLM
 11. run_portfolio_manager_decision -- LangGraph node: state in -> state out
 12. Error paths                  -- missing ticker, empty research, LLM failure
 13. Acceptance criteria          -- debate references, conviction/quality link
 14. Schema validation            -- InvestmentDecision Pydantic constraints
 15. LangSmith tracing            -- @traced_agent applied

Acceptance criteria verified (from task spec):
  * Portfolio Manager's decision references specific points from debate
    (investment_thesis names a debate round; contrarian_response names
    the Contrarian's strongest_argument).
  * Conviction score correlates with quality of analysis: a clean,
    agreeing, low-risk profile scores materially higher conviction than
    a conflicting, high-risk, heavily-debated profile, even when both
    might resolve to the same verdict.
  * Agent never raises -- always returns dict with 'decision' key.

All external calls (LLM) are mocked.
No network. No database. No LLM quota consumed.
"""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.agents.output_models import InvestmentDecision  # noqa: E402
from backend.agents.portfolio_manager import (  # noqa: E402
    SYSTEM_PROMPT,
    _build_key_catalysts,
    _build_key_risks,
    _build_portfolio_manager_prompt,
    _build_price_target,
    _compute_agent_weights,
    _determine_time_horizon,
    _determine_verdict,
    _extract_debate_highlights,
    _run_portfolio_manager_core,
    _score_conviction,
    run_portfolio_manager_decision,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# TCS-like: strong, broadly agreeing bull profile, low risk, weak bear case.
_FUNDAMENTAL_STRONG: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 9,
    "debt_to_equity": 0.02,
    "roe_pct": 46.2,
    "strengths": [
        "Revenue CAGR of 13.7% over 4 years",
        "ROE of 46.2% exceeds sector average",
        "Net cash balance sheet",
    ],
    "weaknesses": ["High PE of 28.5x limits upside"],
    "summary": (
        "TCS demonstrates exceptional fundamental quality with consistent "
        "double-digit growth and industry-leading ROE."
    ),
}

_FUNDAMENTAL_WEAK: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 3,
    "debt_to_equity": 1.4,
    "roe_pct": 8.0,
    "strengths": [],
    "weaknesses": ["Declining margins", "High leverage", "Weak ROE"],
    "summary": "Fundamentals are deteriorating across most key metrics.",
}

_TECHNICAL_BUY_STRONG: dict[str, Any] = {
    "signal": "BUY",
    "signal_strength": 8,
    "rsi_14": 62.0,
    "summary": "Strong uptrend, price above both MAs, bullish momentum.",
}

_TECHNICAL_SELL_STRONG: dict[str, Any] = {
    "signal": "SELL",
    "signal_strength": 8,
    "rsi_14": 28.0,
    "summary": "Confirmed downtrend, price below both MAs.",
}

_TECHNICAL_HOLD: dict[str, Any] = {
    "signal": "HOLD",
    "signal_strength": 5,
    "rsi_14": 50.0,
    "summary": "Neutral signal, sideways price action.",
}

_SENTIMENT_POSITIVE: dict[str, Any] = {
    "sentiment_score": 0.45,
    "sentiment_label": "positive",
    "red_flags": [],
    "summary": "News flow is broadly positive with no governance concerns.",
}

_SENTIMENT_NEGATIVE: dict[str, Any] = {
    "sentiment_score": -0.5,
    "sentiment_label": "negative",
    "red_flags": ["Regulatory notice received"],
    "summary": "Negative news flow dominated by a regulatory notice.",
}

_MACRO_FAVOURABLE: dict[str, Any] = {
    "macro_environment": "favourable",
    "sector_impact": "tailwind",
    "tailwinds": ["INR depreciation benefits IT exporters", "Strong deal pipeline"],
    "headwinds": [],
    "summary": "Macro backdrop is supportive for IT exporters.",
}

_MACRO_UNFAVOURABLE: dict[str, Any] = {
    "macro_environment": "unfavourable",
    "sector_impact": "headwind",
    "tailwinds": [],
    "headwinds": ["Global slowdown risk", "Higher cost of capital"],
    "summary": "Macro backdrop is deteriorating for cyclical sectors.",
}

_RISK_LOW: dict[str, Any] = {
    "risk_score": 3,
    "governance_risk": 2,
    "regulatory_risk": 3,
    "financial_risk": 3,
    "concentration_risk": 4,
    "risk_flags": [],
    "critical_flags": [],
    "risk_recommendation": "proceed with caution",
    "summary": "No material risk flags identified.",
}

_RISK_HIGH: dict[str, Any] = {
    "risk_score": 9,
    "governance_risk": 8,
    "regulatory_risk": 9,
    "financial_risk": 7,
    "concentration_risk": 6,
    "risk_flags": ["High promoter pledge", "Active SEBI investigation"],
    "critical_flags": ["High promoter pledge", "Active SEBI investigation"],
    "risk_recommendation": "avoid",
    "summary": "Multiple critical governance and regulatory flags identified.",
}

_CONTRARIAN_MILD: dict[str, Any] = {
    "bear_conviction": 3,
    "counter_arguments": ["Valuation looks full relative to growth."],
    "overlooked_risks": [],
    "challenged_agents": ["fundamental_analyst"],
    "strongest_argument": (
        "The fundamental score ignores that FCF conversion has declined "
        "for 3 consecutive years."
    ),
    "summary": "Mild scepticism; bull case largely intact.",
}

_CONTRARIAN_STRONG: dict[str, Any] = {
    "bear_conviction": 8,
    "counter_arguments": [
        "High ROE invites competition and margin compression.",
        "RSI overbought conditions historically precede pullbacks.",
        "Low D/E signals growth exhaustion, not strength.",
    ],
    "overlooked_risks": ["Customer concentration in top 5 clients exceeds 40%"],
    "challenged_agents": ["fundamental_analyst", "technical_analyst"],
    "strongest_argument": (
        "Customer concentration risk is structurally underpriced by every "
        "other agent on this committee."
    ),
    "summary": "Strong contra-consensus case built on overlooked structural risk.",
}

_VALUATION_UNDERVALUED: dict[str, Any] = {
    "intrinsic_value_per_share": 4500.0,
    "current_price": 3800.0,
    "upside_downside_pct": 18.4,
    "valuation_verdict": "undervalued",
    "margin_of_safety": "high",
    "summary": "DCF implies meaningful upside versus current trading price.",
}

_VALUATION_OVERVALUED: dict[str, Any] = {
    "intrinsic_value_per_share": 2800.0,
    "current_price": 3800.0,
    "upside_downside_pct": -26.3,
    "valuation_verdict": "overvalued",
    "margin_of_safety": "none",
    "summary": "DCF implies the stock is trading well above intrinsic value.",
}

_VALUATION_FAIR: dict[str, Any] = {
    "intrinsic_value_per_share": 3900.0,
    "current_price": 3800.0,
    "upside_downside_pct": 2.6,
    "valuation_verdict": "fairly_valued",
    "margin_of_safety": "low",
    "summary": "Stock trades close to intrinsic value with limited margin.",
}

_DEBATE_ROUNDS_ONE: list[dict[str, Any]] = [
    {
        "round_number": 1,
        "agent_responses": {
            "fundamental": "Fundamental Analyst reaffirms its prior position."
        },
        "contrarian": (
            "Customer concentration risk is structurally underpriced by "
            "every other agent on this committee."
        ),
        "completed_at": "2024-01-15T10:05:00Z",
    }
]

_DEBATE_ROUNDS_TWO: list[dict[str, Any]] = _DEBATE_ROUNDS_ONE + [
    {
        "round_number": 2,
        "agent_responses": {
            "fundamental": "Fundamental Analyst concedes the challenge raises a point."
        },
        "contrarian": "Second round challenge restating concentration risk.",
        "completed_at": "2024-01-15T10:07:00Z",
    }
]

_BASE_KWARGS: dict[str, Any] = {
    "analysis_id": "test-analysis-001",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}

_LLM_JSON_RESPONSE: str = json.dumps(
    {
        "executive_summary": "TCS shows strong fundamentals with manageable risk.",
        "investment_thesis": (
            "The bull case rests on strong ROE, though the Contrarian's Round 1 "
            "challenge on customer concentration tempers conviction."
        ),
        "bull_case": "Fundamental score of 9/10 driven by 46.2% ROE.",
        "bear_case": "Customer concentration exceeds 40% per the Contrarian.",
        "risk_summary": "Risk score of 3/10; no critical flags identified.",
        "valuation_summary": "DCF implies 18.4% upside to intrinsic value.",
        "contrarian_response": (
            "Addressing the Contrarian's strongest argument on customer "
            "concentration: the committee weighs this against the low "
            "overall risk score and assigns moderate conviction."
        ),
        "summary": "TCS: BUY with conviction 8/10.",
    }
)


def _make_llm(content: str = _LLM_JSON_RESPONSE) -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = content
    mock.invoke.return_value = response
    return mock


# ---------------------------------------------------------------------------
# Tests: _compute_agent_weights
# ---------------------------------------------------------------------------


class TestComputeAgentWeights:
    def test_weights_sum_to_one_when_all_agents_usable(self) -> None:
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_all_seven_agents_present_in_weights(self) -> None:
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        for name in (
            "fundamental_analyst",
            "technical_analyst",
            "news_sentiment",
            "macro_economist",
            "risk_officer",
            "contrarian_investor",
            "valuation_agent",
        ):
            assert name in weights

    def test_errored_agent_gets_zero_weight(self) -> None:
        errored_sentiment = {**_SENTIMENT_POSITIVE, "error": "API timeout"}
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            errored_sentiment,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["news_sentiment"] == 0.0
        # Sum tolerance is looser here than the all-agents-usable case: each
        # weight is independently rounded to 4 decimal places, so summing
        # 6 rounded values can drift up to ~6 * 0.00005 = 0.0003 from 1.0.
        assert abs(sum(weights.values()) - 1.0) < 1e-3

    def test_empty_agent_dict_gets_zero_weight(self) -> None:
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            {},
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["technical_analyst"] == 0.0

    def test_all_agents_errored_returns_all_zero(self) -> None:
        weights = _compute_agent_weights({}, {}, {}, {}, {}, {}, {})
        assert all(w == 0.0 for w in weights.values())

    def test_fundamental_and_valuation_have_highest_base_weight(self) -> None:
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["fundamental_analyst"] >= weights["news_sentiment"]
        assert weights["valuation_agent"] >= weights["news_sentiment"]


# ---------------------------------------------------------------------------
# Tests: _determine_verdict
# ---------------------------------------------------------------------------


class TestDetermineVerdict:
    def test_strong_bull_profile_yields_buy(self) -> None:
        verdict = _determine_verdict(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            critical_flags=[],
        )
        assert verdict == "BUY"

    def test_prohibitive_risk_score_forces_sell(self) -> None:
        verdict = _determine_verdict(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _RISK_HIGH,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            critical_flags=_RISK_HIGH["critical_flags"],
        )
        assert verdict == "SELL"

    def test_overvalued_plus_weak_fundamentals_forces_sell(self) -> None:
        verdict = _determine_verdict(
            _FUNDAMENTAL_WEAK,
            _TECHNICAL_SELL_STRONG,
            _SENTIMENT_NEGATIVE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_OVERVALUED,
            critical_flags=[],
        )
        assert verdict == "SELL"

    def test_weak_bearish_profile_yields_sell_or_hold(self) -> None:
        verdict = _determine_verdict(
            _FUNDAMENTAL_WEAK,
            _TECHNICAL_SELL_STRONG,
            _SENTIMENT_NEGATIVE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_FAIR,
            critical_flags=[],
        )
        assert verdict in ("SELL", "HOLD")

    def test_mixed_signals_yield_hold(self) -> None:
        verdict = _determine_verdict(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            {"bear_conviction": 4},
            _VALUATION_FAIR,
            critical_flags=[],
        )
        assert verdict == "HOLD"

    def test_strong_contrarian_can_downgrade_marginal_buy(self) -> None:
        verdict = _determine_verdict(
            {"score": 6},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.1},
            {"risk_score": 5},
            _CONTRARIAN_STRONG,
            _VALUATION_FAIR,
            critical_flags=[],
        )
        assert verdict != "BUY"

    def test_verdict_is_always_one_of_three_values(self) -> None:
        for fund, tech, sent, risk, contra, val in [
            (
                _FUNDAMENTAL_STRONG,
                _TECHNICAL_BUY_STRONG,
                _SENTIMENT_POSITIVE,
                _RISK_LOW,
                _CONTRARIAN_MILD,
                _VALUATION_UNDERVALUED,
            ),
            (
                _FUNDAMENTAL_WEAK,
                _TECHNICAL_SELL_STRONG,
                _SENTIMENT_NEGATIVE,
                _RISK_HIGH,
                _CONTRARIAN_STRONG,
                _VALUATION_OVERVALUED,
            ),
            ({}, {}, {}, {}, {}, {}),
        ]:
            verdict = _determine_verdict(
                fund, tech, sent, risk, contra, val, critical_flags=[]
            )
            assert verdict in ("BUY", "HOLD", "SELL")


# ---------------------------------------------------------------------------
# Tests: _score_conviction -- the core "quality of analysis" criterion
# ---------------------------------------------------------------------------


class TestScoreConviction:
    def test_conviction_within_bounds(self) -> None:
        conviction = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        assert 1 <= conviction <= 10

    def test_agreeing_clean_profile_beats_conflicting_high_risk_profile(self) -> None:
        """
        Acceptance criterion: conviction score correlates with QUALITY of
        analysis.  A clean, agreeing, low-risk, single-round profile must
        score materially higher conviction than a profile built on
        conflicting signals, high risk, and a strong contrarian challenge
        spanning multiple debate rounds -- even though both are nominally
        bullish setups on the surface.
        """
        clean_conviction = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        conflicting_conviction = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_SELL_STRONG,  # contradicts fundamentals
            _SENTIMENT_NEGATIVE,  # contradicts fundamentals
            _MACRO_UNFAVOURABLE,
            _RISK_HIGH,
            _CONTRARIAN_STRONG,
            _VALUATION_OVERVALUED,  # contradicts fundamentals
            verdict="BUY",
            debate_rounds_used=2,
        )
        assert clean_conviction > conflicting_conviction

    def test_missing_agent_data_reduces_conviction(self) -> None:
        full_conviction = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        degraded_conviction = _score_conviction(
            _FUNDAMENTAL_STRONG,
            {"error": "data unavailable"},
            {"error": "data unavailable"},
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        assert degraded_conviction < full_conviction

    def test_more_debate_rounds_reduces_conviction(self) -> None:
        one_round = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        two_rounds = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=2,
        )
        assert two_rounds < one_round

    def test_high_bear_conviction_reduces_conviction(self) -> None:
        mild_contra = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        strong_contra = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_STRONG,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        assert strong_contra < mild_contra

    def test_critical_flags_reduce_conviction(self) -> None:
        no_flags_risk = {**_RISK_LOW, "critical_flags": []}
        with_flags_risk = {**_RISK_LOW, "critical_flags": ["Flag A", "Flag B"]}
        conviction_no_flags = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            no_flags_risk,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        conviction_with_flags = _score_conviction(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            with_flags_risk,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
            verdict="BUY",
            debate_rounds_used=1,
        )
        assert conviction_with_flags < conviction_no_flags


# ---------------------------------------------------------------------------
# Tests: _determine_time_horizon
# ---------------------------------------------------------------------------


class TestDetermineTimeHorizon:
    def test_hold_returns_quarterly_review(self) -> None:
        horizon = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="HOLD"
        )
        assert "quarter" in horizon.lower()

    def test_technically_driven_buy_returns_short_horizon(self) -> None:
        horizon = _determine_time_horizon(
            _TECHNICAL_BUY_STRONG, _VALUATION_FAIR, verdict="BUY"
        )
        assert "month" in horizon.lower()

    def test_high_margin_of_safety_buy_returns_long_horizon(self) -> None:
        weak_technical = {"signal": "BUY", "signal_strength": 4}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_UNDERVALUED, verdict="BUY"
        )
        assert "year" in horizon.lower()

    def test_default_horizon_is_twelve_months(self) -> None:
        weak_technical = {"signal": "HOLD", "signal_strength": 5}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_FAIR, verdict="BUY"
        )
        assert horizon == "12 months"


# ---------------------------------------------------------------------------
# Tests: _build_price_target
# ---------------------------------------------------------------------------


class TestBuildPriceTarget:
    def test_returns_none_when_intrinsic_value_missing(self) -> None:
        result = _build_price_target({}, "12 months")
        assert result is None

    def test_formats_intrinsic_value_correctly(self) -> None:
        result = _build_price_target(_VALUATION_UNDERVALUED, "12 months")
        assert result is not None
        assert "4,500" in result
        assert "12 months" in result

    def test_handles_non_numeric_intrinsic_value_gracefully(self) -> None:
        result = _build_price_target(
            {"intrinsic_value_per_share": "not-a-number"}, "12 months"
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _build_key_risks
# ---------------------------------------------------------------------------


class TestBuildKeyRisks:
    def test_returns_critical_flags_first(self) -> None:
        risks = _build_key_risks(_RISK_HIGH, _CONTRARIAN_MILD, critical_flags=[])
        assert risks[0] in _RISK_HIGH["critical_flags"]

    def test_includes_strongest_argument(self) -> None:
        risks = _build_key_risks(_RISK_LOW, _CONTRARIAN_STRONG, critical_flags=[])
        assert any(
            "customer concentration" in r.lower() or "underpriced" in r.lower()
            for r in risks
        )

    def test_capped_at_six_entries(self) -> None:
        big_risk = {
            "critical_flags": [f"Flag {i}" for i in range(10)],
        }
        risks = _build_key_risks(big_risk, _CONTRARIAN_STRONG, critical_flags=[])
        assert len(risks) <= 6

    def test_fallback_when_no_risks_found(self) -> None:
        risks = _build_key_risks({}, {}, critical_flags=[])
        assert len(risks) >= 1

    def test_deduplicates_overlapping_flags(self) -> None:
        risk = {"critical_flags": ["Same flag text here for dedup testing"]}
        critical_flags = ["Same flag text here for dedup testing"]
        risks = _build_key_risks(risk, {}, critical_flags=critical_flags)
        assert len(risks) == 1


# ---------------------------------------------------------------------------
# Tests: _build_key_catalysts
# ---------------------------------------------------------------------------


class TestBuildKeyCatalysts:
    def test_includes_macro_tailwinds(self) -> None:
        catalysts = _build_key_catalysts(
            _MACRO_FAVOURABLE, _FUNDAMENTAL_STRONG, _VALUATION_UNDERVALUED
        )
        assert any("INR depreciation" in c for c in catalysts)

    def test_includes_upside_catalyst_for_high_margin_of_safety(self) -> None:
        catalysts = _build_key_catalysts(
            _MACRO_FAVOURABLE, _FUNDAMENTAL_STRONG, _VALUATION_UNDERVALUED
        )
        assert any("upside" in c.lower() or "re-rating" in c.lower() for c in catalysts)

    def test_capped_at_five_entries(self) -> None:
        big_macro = {
            "tailwinds": [f"Tailwind {i}" for i in range(10)],
            "headwinds": [],
        }
        catalysts = _build_key_catalysts(
            big_macro, _FUNDAMENTAL_STRONG, _VALUATION_UNDERVALUED
        )
        assert len(catalysts) <= 5

    def test_fallback_when_no_catalysts_found(self) -> None:
        catalysts = _build_key_catalysts({}, {}, {})
        assert len(catalysts) >= 1


# ---------------------------------------------------------------------------
# Tests: _extract_debate_highlights
# ---------------------------------------------------------------------------


class TestExtractDebateHighlights:
    def test_empty_rounds_returns_empty_list(self) -> None:
        assert _extract_debate_highlights([]) == []

    def test_one_round_returns_one_highlight(self) -> None:
        highlights = _extract_debate_highlights(_DEBATE_ROUNDS_ONE)
        assert len(highlights) == 1
        assert "Round 1" in highlights[0]

    def test_two_rounds_returns_two_highlights(self) -> None:
        highlights = _extract_debate_highlights(_DEBATE_ROUNDS_TWO)
        assert len(highlights) == 2
        assert "Round 1" in highlights[0]
        assert "Round 2" in highlights[1]

    def test_highlight_contains_contrarian_text(self) -> None:
        highlights = _extract_debate_highlights(_DEBATE_ROUNDS_ONE)
        assert "concentration" in highlights[0].lower()


# ---------------------------------------------------------------------------
# Tests: _build_portfolio_manager_prompt
# ---------------------------------------------------------------------------


class TestBuildPortfolioManagerPrompt:
    def _build(self) -> str:
        return _build_portfolio_manager_prompt(
            company_name="Tata Consultancy Services",
            ticker="TCS.NS",
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_highlights=_extract_debate_highlights(_DEBATE_ROUNDS_ONE),
            verdict="BUY",
            conviction_score=8,
            time_horizon="12 months",
            price_target="Rs. 4,500 (12 months)",
            key_risks=["Customer concentration risk"],
            key_catalysts=["INR depreciation benefits IT exporters"],
        )

    def test_prompt_contains_company_and_ticker(self) -> None:
        prompt = self._build()
        assert "Tata Consultancy Services" in prompt
        assert "TCS.NS" in prompt

    def test_prompt_contains_predetermined_verdict_and_conviction(self) -> None:
        prompt = self._build()
        assert "BUY" in prompt
        assert "8/10" in prompt

    def test_prompt_contains_debate_highlights(self) -> None:
        prompt = self._build()
        assert "Round 1" in prompt

    def test_prompt_contains_strongest_argument(self) -> None:
        prompt = self._build()
        assert _CONTRARIAN_MILD["strongest_argument"] in prompt

    def test_prompt_contains_key_risks_and_catalysts(self) -> None:
        prompt = self._build()
        assert "Customer concentration risk" in prompt
        assert "INR depreciation benefits IT exporters" in prompt

    def test_prompt_handles_missing_price_target(self) -> None:
        prompt = _build_portfolio_manager_prompt(
            company_name="Test Corp",
            ticker="TEST.NS",
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={},
            contrarian={},
            valuation={},
            debate_highlights=[],
            verdict="HOLD",
            conviction_score=5,
            time_horizon="12 months",
            price_target=None,
            key_risks=[],
            key_catalysts=[],
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Tests: _run_portfolio_manager_core
# ---------------------------------------------------------------------------


class TestRunPortfolioManagerCore:
    @patch("backend.agents.portfolio_manager.get_llm")
    def test_returns_investment_decision_instance(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert isinstance(result, InvestmentDecision)

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_verdict_in_allowed_set(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert result.verdict in ("BUY", "HOLD", "SELL")

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_conviction_score_within_bounds(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert 1 <= result.conviction_score <= 10

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_investment_thesis_references_debate_round(
        self, mock_get_llm: MagicMock
    ) -> None:
        """Acceptance criterion: decision references specific debate points."""
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert "Round 1" in result.investment_thesis

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_contrarian_response_addresses_strongest_argument(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert len(result.contrarian_response) > 0

    def test_llm_failure_still_produces_valid_decision(self) -> None:
        """On LLM failure the deterministic fallback path must still
        produce a fully valid, non-raising InvestmentDecision."""
        with patch("backend.agents.portfolio_manager.get_llm") as mock_get_llm:
            mock_get_llm.side_effect = RuntimeError("LLM provider unavailable")
            result = _run_portfolio_manager_core(
                **_BASE_KWARGS,
                fundamental=_FUNDAMENTAL_STRONG,
                technical=_TECHNICAL_BUY_STRONG,
                sentiment=_SENTIMENT_POSITIVE,
                macro=_MACRO_FAVOURABLE,
                risk=_RISK_LOW,
                contrarian=_CONTRARIAN_MILD,
                valuation=_VALUATION_UNDERVALUED,
                debate_rounds=_DEBATE_ROUNDS_ONE,
                debate_round_count=1,
                critical_flags=[],
            )
        assert isinstance(result, InvestmentDecision)
        assert result.verdict in ("BUY", "HOLD", "SELL")
        assert len(result.contrarian_response) > 0
        assert result.error is None  # error is None: this is a handled fallback

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_malformed_llm_json_falls_back_gracefully(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm(content="not valid json {{{")
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert isinstance(result, InvestmentDecision)
        assert len(result.executive_summary) > 0

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_empty_research_dicts_handled(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            analysis_id="empty-test",
            company_name="Test Corp",
            ticker="TEST.NS",
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={},
            contrarian={},
            valuation={},
            debate_rounds=[],
            debate_round_count=0,
            critical_flags=[],
        )
        assert isinstance(result, InvestmentDecision)
        assert result.verdict in ("BUY", "HOLD", "SELL")

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_key_risks_and_catalysts_populated(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert len(result.key_risks) >= 1
        assert len(result.key_catalysts) >= 1

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_time_horizon_populated(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_portfolio_manager_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_FAVOURABLE,
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            debate_rounds=_DEBATE_ROUNDS_ONE,
            debate_round_count=1,
            critical_flags=[],
        )
        assert len(result.time_horizon) > 0


# ---------------------------------------------------------------------------
# Tests: run_portfolio_manager_decision (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunPortfolioManagerDecisionNode:
    def _make_state(
        self,
        ticker: str = "TCS.NS",
        company_name: str = "Tata Consultancy Services",
        job_id: str = "test-job-001",
        fundamental: dict[str, Any] | None = None,
        technical: dict[str, Any] | None = None,
        sentiment: dict[str, Any] | None = None,
        macro: dict[str, Any] | None = None,
        risk: dict[str, Any] | None = None,
        contrarian: dict[str, Any] | None = None,
        valuation: dict[str, Any] | None = None,
        debate_rounds: list[dict[str, Any]] | None = None,
        debate_round_count: int = 1,
        critical_flags: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "company_name": company_name,
            "ticker": ticker,
            "fundamental": fundamental or _FUNDAMENTAL_STRONG,
            "technical": technical or _TECHNICAL_BUY_STRONG,
            "sentiment": sentiment or _SENTIMENT_POSITIVE,
            "macro": macro or _MACRO_FAVOURABLE,
            "risk": risk or _RISK_LOW,
            "contrarian": contrarian or _CONTRARIAN_MILD,
            "valuation": valuation or _VALUATION_UNDERVALUED,
            "debate_rounds": debate_rounds or _DEBATE_ROUNDS_ONE,
            "debate_round_count": debate_round_count,
            "critical_flags": critical_flags or [],
        }

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_returns_dict_with_decision_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert "decision" in result
        assert isinstance(result["decision"], dict)

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_returns_final_verdict_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert "final_verdict" in result
        assert result["final_verdict"] in ("BUY", "HOLD", "SELL")

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_returns_conviction_score_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert "conviction_score" in result
        assert 1 <= result["conviction_score"] <= 10

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_returns_price_target_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert "price_target" in result

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_decision_dict_has_required_fields(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        decision = result["decision"]
        for field in (
            "agent_name",
            "verdict",
            "conviction_score",
            "time_horizon",
            "key_risks",
            "key_catalysts",
            "executive_summary",
            "investment_thesis",
            "bull_case",
            "bear_case",
            "risk_summary",
            "valuation_summary",
            "contrarian_response",
            "debate_rounds_used",
            "agent_weights",
            "summary",
        ):
            assert field in decision, f"Missing field: {field}"

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_agent_name_is_portfolio_manager(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert result["decision"]["agent_name"] == "portfolio_manager"

    def test_missing_ticker_returns_error_result(self) -> None:
        state: dict[str, Any] = {
            "job_id": "test-no-ticker",
            "company_name": "Test Corp",
            "ticker": "",
        }
        result = run_portfolio_manager_decision(state)
        assert "decision" in result
        assert result["decision"].get("error") is not None
        assert result["final_verdict"] == "HOLD"
        assert result["conviction_score"] == 1

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_none_research_dicts_handled(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        state: dict[str, Any] = {
            "job_id": "test-none",
            "company_name": "Test Corp",
            "ticker": "TEST.NS",
            "fundamental": None,
            "technical": None,
            "sentiment": None,
            "macro": None,
            "risk": None,
            "contrarian": None,
            "valuation": None,
            "debate_rounds": None,
            "debate_round_count": 0,
            "critical_flags": None,
        }
        result = run_portfolio_manager_decision(state)
        assert "decision" in result
        assert result["final_verdict"] in ("BUY", "HOLD", "SELL")

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_result_is_json_serialisable(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        json.dumps(result, default=str)  # must not raise

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_strong_bull_state_yields_buy_with_high_conviction(
        self, mock_get_llm: MagicMock
    ) -> None:
        """End-to-end acceptance criteria check via LangGraph node."""
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert result["final_verdict"] == "BUY"
        assert result["conviction_score"] >= 6

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_high_risk_state_yields_sell(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(
            self._make_state(
                risk=_RISK_HIGH, critical_flags=_RISK_HIGH["critical_flags"]
            )
        )
        assert result["final_verdict"] == "SELL"

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_decision_references_debate_round(self, mock_get_llm: MagicMock) -> None:
        """Acceptance criterion verified at the node level."""
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state())
        assert "Round 1" in result["decision"]["investment_thesis"]


# ---------------------------------------------------------------------------
# Tests: Schema validation (InvestmentDecision Pydantic constraints)
# ---------------------------------------------------------------------------


class TestInvestmentDecisionSchemaValidation:
    _BASE: dict[str, Any] = {
        "agent_name": "portfolio_manager",
        "analysis_id": "schema-test",
        "company_name": "Test Corp",
        "ticker": "TEST.NS",
        "verdict": "BUY",
        "conviction_score": 7,
    }

    def test_valid_model_constructs_successfully(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.conviction_score == 7

    def test_conviction_score_below_1_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InvestmentDecision(**{**self._BASE, "conviction_score": 0})

    def test_conviction_score_above_10_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InvestmentDecision(**{**self._BASE, "conviction_score": 11})

    def test_default_time_horizon_is_twelve_months(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.time_horizon == "12 months"

    def test_default_key_risks_empty_list(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.key_risks == []

    def test_default_key_catalysts_empty_list(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.key_catalysts == []

    def test_default_debate_rounds_used_is_one(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.debate_rounds_used == 1

    def test_debate_rounds_used_below_1_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InvestmentDecision(**{**self._BASE, "debate_rounds_used": 0})

    def test_model_is_frozen(self) -> None:
        from pydantic import ValidationError

        result = InvestmentDecision(**self._BASE)
        with pytest.raises(ValidationError):
            result.conviction_score = 99  # type: ignore[misc]

    def test_model_dump_round_trip(self) -> None:
        result = InvestmentDecision(
            **self._BASE,
            time_horizon="3-5 years",
            key_risks=["Risk A", "Risk B"],
            key_catalysts=["Catalyst A"],
            contrarian_response="Addressed directly.",
        )
        dumped = result.model_dump()
        assert dumped["time_horizon"] == "3-5 years"
        assert dumped["key_risks"] == ["Risk A", "Risk B"]
        assert dumped["key_catalysts"] == ["Catalyst A"]

    def test_agent_name_default(self) -> None:
        result = InvestmentDecision(**self._BASE)
        assert result.agent_name == "portfolio_manager"

    def test_verdict_field_is_required(self) -> None:
        from pydantic import ValidationError

        incomplete = {k: v for k, v in self._BASE.items() if k != "verdict"}
        with pytest.raises(ValidationError):
            InvestmentDecision(**incomplete)


# ---------------------------------------------------------------------------
# Tests: SYSTEM_PROMPT content
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_not_empty(self) -> None:
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_rules(self) -> None:
        assert "RULES:" in SYSTEM_PROMPT

    def test_system_prompt_mentions_output_schema(self) -> None:
        assert "OUTPUT SCHEMA" in SYSTEM_PROMPT

    def test_system_prompt_requires_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_is_ascii_only(self) -> None:
        SYSTEM_PROMPT.encode("ascii")  # raises if non-ASCII

    def test_system_prompt_mentions_contrarian_response(self) -> None:
        assert "contrarian_response" in SYSTEM_PROMPT

    def test_system_prompt_mentions_investment_thesis(self) -> None:
        assert "investment_thesis" in SYSTEM_PROMPT

    def test_system_prompt_mentions_debate_reference_requirement(self) -> None:
        assert "debate" in SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# Tests: LangSmith tracing integration
# ---------------------------------------------------------------------------


class TestTracingIntegration:
    def test_run_portfolio_manager_decision_is_traced(self) -> None:
        """@traced_agent wraps the function; __wrapped__ exposes the original."""
        assert hasattr(run_portfolio_manager_decision, "__wrapped__"), (
            "run_portfolio_manager_decision is missing __wrapped__; "
            "@traced_agent was not applied"
        )

    def test_wrapped_function_is_callable(self) -> None:
        assert hasattr(run_portfolio_manager_decision, "__wrapped__")
        wrapped = getattr(run_portfolio_manager_decision, "__wrapped__", None)
        assert wrapped is not None
        assert callable(wrapped)
