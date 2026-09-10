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
    _ADVERSARIAL_AGENTS,
    _BASE_AGENT_WEIGHTS,
    _MAX_ADVERSARIAL_WEIGHT_MULTIPLIER,
    SYSTEM_PROMPT,
    _build_key_catalysts,
    _build_key_risks,
    _build_portfolio_manager_prompt,
    _build_price_target,
    _build_relative_price_target,
    _compute_agent_weights,
    _data_completeness,
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

# A typed, named stand-in for "no macro signal" -- used instead of a bare
# `{}` literal so every column in a parametrised call site is a
# consistently-typed dict[str, Any], matching every other agent's fixture
# above. A bare `{}` repeated across multiple rows of the same unpacked
# tuple loop gives mypy nothing to infer the loop variable's element type
# from (CI: "Need type annotation for 'macro'").
_MACRO_NEUTRAL: dict[str, Any] = {}

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

# B2: no DCF intrinsic value (e.g. insufficient FCF history), but peer PE
# data is present -- shaped like a real ValuationOutput.model_dump() with
# intrinsic_value_per_share=None.
_VALUATION_NO_DCF_WITH_PEERS: dict[str, Any] = {
    "intrinsic_value_per_share": None,
    "current_price": 3800.0,
    "upside_downside_pct": None,
    "valuation_verdict": "fairly_valued",
    "margin_of_safety": None,
    "pe_ratio": 22.0,
    "sector_avg_pe": 26.0,
    "pb_ratio": 4.0,
    "sector_avg_pb": 4.5,
    "summary": "DCF unavailable; relative valuation vs. peers used instead.",
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

    def test_insufficient_fundamental_data_quality_gets_zero_weight(self) -> None:
        """T-082: fundamental_analyst is excluded (not just neutral-weighted)
        when its data_quality is 'insufficient', even though it produced no
        'error' and would otherwise pass the usability check."""
        fundamental_insufficient = {
            **_FUNDAMENTAL_STRONG,
            "score": None,
            "data_quality": "insufficient",
        }
        weights = _compute_agent_weights(
            fundamental_insufficient,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["fundamental_analyst"] == 0.0
        assert abs(sum(weights.values()) - 1.0) < 1e-3

    def test_sufficient_fundamental_data_quality_keeps_normal_weight(self) -> None:
        """Regression guard: explicit data_quality='sufficient' must not
        disable the fundamental analyst's normal weight."""
        fundamental_sufficient = {**_FUNDAMENTAL_STRONG, "data_quality": "sufficient"}
        weights = _compute_agent_weights(
            fundamental_sufficient,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["fundamental_analyst"] > 0.0

    def test_missing_data_quality_key_keeps_normal_weight(self) -> None:
        """Backward compatibility: fundamental dicts with no data_quality key
        at all (pre-T-081 shape) behave exactly as before."""
        assert "data_quality" not in _FUNDAMENTAL_STRONG
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["fundamental_analyst"] > 0.0


# ---------------------------------------------------------------------------
# Tests: _compute_agent_weights -- adversarial weight cap (bug #9, T-087)
#
# Reproduces the "evidence weighting" screenshot from the refinement work
# order: Fundamental 0%, Technical 0%, News/Macro 0%, and Risk + Contrarian
# combining to a majority share purely because the bullish research agents
# lacked data on a cold run -- not because Risk/Contrarian said anything
# more convincing than usual.
# ---------------------------------------------------------------------------


class TestComputeAgentWeightsAdversarialCap:
    def test_adversarial_seats_capped_when_only_they_and_valuation_are_usable(
        self,
    ) -> None:
        """
        Before the fix: with fundamental/technical/macro/news all dropped
        out, redistributing their combined 0.50 base weight over
        {risk: 0.15, contrarian: 0.15, valuation: 0.20} (total 0.50)
        pushes risk_officer and contrarian_investor to 0.30 each (60%
        combined) -- a bearish-looking committee purely from data
        dropout. After the fix, each adversarial seat is capped at
        0.15 * 1.5 = 0.225, and the 0.15 combined excess flows to
        valuation_agent instead.
        """
        weights = _compute_agent_weights(
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={"risk_score": 6},
            contrarian={"bear_conviction": 5},
            valuation=_VALUATION_FAIR,
        )
        risk_cap = (
            _BASE_AGENT_WEIGHTS["risk_officer"] * _MAX_ADVERSARIAL_WEIGHT_MULTIPLIER
        )
        contrarian_cap = (
            _BASE_AGENT_WEIGHTS["contrarian_investor"]
            * _MAX_ADVERSARIAL_WEIGHT_MULTIPLIER
        )
        assert weights["risk_officer"] <= risk_cap + 1e-9
        assert weights["contrarian_investor"] <= contrarian_cap + 1e-9
        assert weights["valuation_agent"] > weights["risk_officer"]
        assert weights["valuation_agent"] > weights["contrarian_investor"]
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)

    def test_combined_adversarial_share_no_longer_majority(self) -> None:
        """Direct regression for the observed bug: Risk + Contrarian must
        no longer combine to a majority (>50%) of the committee weight
        purely because the bullish agents lacked data."""
        weights = _compute_agent_weights(
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={"risk_score": 6},
            contrarian={"bear_conviction": 5},
            valuation=_VALUATION_FAIR,
        )
        combined_adversarial = sum(weights[name] for name in _ADVERSARIAL_AGENTS)
        assert combined_adversarial < 0.5

    def test_cap_not_applied_when_no_non_adversarial_agent_is_usable(self) -> None:
        """
        Edge case: if Risk and Contrarian are the ONLY usable agents, there
        is nowhere to redistribute the excess without violating
        sum(weights) == 1.0, so the cap is intentionally not enforced —
        each still gets exactly half.
        """
        weights = _compute_agent_weights(
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={"risk_score": 6},
            contrarian={"bear_conviction": 5},
            valuation={},
        )
        assert weights["risk_officer"] == pytest.approx(0.5, abs=1e-6)
        assert weights["contrarian_investor"] == pytest.approx(0.5, abs=1e-6)
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_cap_does_not_trigger_when_all_agents_usable(self) -> None:
        """Sanity check: the common, healthy-data-availability case must be
        completely unaffected by the cap (already covered by
        TestComputeAgentWeights, restated here as an explicit cap-specific
        regression)."""
        weights = _compute_agent_weights(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_FAVOURABLE,
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_UNDERVALUED,
        )
        assert weights["risk_officer"] == pytest.approx(
            _BASE_AGENT_WEIGHTS["risk_officer"], abs=1e-6
        )
        assert weights["contrarian_investor"] == pytest.approx(
            _BASE_AGENT_WEIGHTS["contrarian_investor"], abs=1e-6
        )


# ---------------------------------------------------------------------------
# Tests: _determine_verdict
# ---------------------------------------------------------------------------


class TestDetermineVerdict:
    def test_strong_bull_profile_yields_buy(self) -> None:
        verdict = _determine_verdict(
            _FUNDAMENTAL_STRONG,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            {},
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
            {},
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
            {},
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_OVERVALUED,
            critical_flags=[],
        )
        assert verdict == "SELL"

    def test_overvalued_plus_insufficient_fundamentals_skips_gate_2(self) -> None:
        """
        T-082: Gate 2 must NOT fire purely because fundamental data was
        insufficient. Without the fix, fund_score defaults to a neutral 5
        (via `or 5`), 5 < 6, and Gate 2 would force SELL as a hard override
        even though the weighted tally on the remaining signals (strong
        technical + positive sentiment offsetting the overvaluation) lands
        at HOLD.
        """
        fundamental_insufficient = {
            "score": None,
            "data_quality": "insufficient",
        }
        verdict = _determine_verdict(
            fundamental_insufficient,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            {},
            _RISK_LOW,
            _CONTRARIAN_MILD,
            _VALUATION_OVERVALUED,
            critical_flags=[],
        )
        assert verdict == "HOLD"

    def test_overvalued_plus_sufficient_but_weak_fundamentals_still_forces_sell(
        self,
    ) -> None:
        """Regression guard: an explicit data_quality='sufficient' weak score
        must still trip Gate 2 as before."""
        fundamental_weak_explicit = {**_FUNDAMENTAL_WEAK, "data_quality": "sufficient"}
        verdict = _determine_verdict(
            fundamental_weak_explicit,
            _TECHNICAL_SELL_STRONG,
            _SENTIMENT_NEGATIVE,
            {},
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
            {},
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
            {},
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
            {},
            {"risk_score": 5},
            _CONTRARIAN_STRONG,
            _VALUATION_FAIR,
            critical_flags=[],
        )
        assert verdict != "BUY"

    def test_verdict_is_always_one_of_three_values(self) -> None:
        for fund, tech, sent, macro, risk, contra, val in [
            (
                _FUNDAMENTAL_STRONG,
                _TECHNICAL_BUY_STRONG,
                _SENTIMENT_POSITIVE,
                _MACRO_NEUTRAL,
                _RISK_LOW,
                _CONTRARIAN_MILD,
                _VALUATION_UNDERVALUED,
            ),
            (
                _FUNDAMENTAL_WEAK,
                _TECHNICAL_SELL_STRONG,
                _SENTIMENT_NEGATIVE,
                _MACRO_NEUTRAL,
                _RISK_HIGH,
                _CONTRARIAN_STRONG,
                _VALUATION_OVERVALUED,
            ),
            ({}, {}, {}, _MACRO_NEUTRAL, {}, {}, {}),
        ]:
            verdict = _determine_verdict(
                fund, tech, sent, macro, risk, contra, val, critical_flags=[]
            )
            assert verdict in ("BUY", "HOLD", "SELL")


class TestDetermineVerdictMacroContribution:
    """
    Audit finding (Section C, unit 9): ``macro`` has a real 0.10 base
    weight in ``_compute_agent_weights`` -- shown to the user as part of
    "How the committee's evidence was weighted" -- but before this fix,
    ``_determine_verdict`` never accepted a ``macro`` parameter at all,
    so a Macro Economist verdict of "unfavourable" contributed nothing
    to the actual BUY/HOLD/SELL decision: two companies identical in
    every other respect but opposite macro environments received the
    exact same verdict. These tests hold every other input fixed at a
    baseline that lands just inside the HOLD band and prove that only
    the macro input flips the verdict across the +-1.5 threshold.
    """

    # Every non-macro input below intentionally contributes exactly the
    # same amount regardless of macro, so the score is provably fixed
    # except for macro_environment's own +-0.75:
    #   fund_score=6         -> (6-5)*0.4        = +0.40
    #   technical HOLD       ->                     0.00
    #   sentiment 0.0        -> 0.0*1.5           =  0.00
    #   valuation fairly_val ->                     0.00
    #   risk_score=5         -> max(0, 5-5)*0.35  =  0.00
    #   bear_conviction=1    -> (1-1)*0.1         =  0.00
    #   critical_flags=[]    ->                     0.00
    # baseline score (macro neutral) = 0.40 -> comfortably inside HOLD.
    _NEUTRAL_TALLY_KWARGS: dict[str, Any] = {
        "fundamental": {"score": 6},
        "technical": {"signal": "HOLD", "signal_strength": 5},
        "sentiment": {"sentiment_score": 0.0},
        "risk": {"risk_score": 5},
        "contrarian": {"bear_conviction": 1},
        "valuation": {"valuation_verdict": "fairly_valued"},
        "critical_flags": [],
    }

    def test_neutral_macro_does_not_move_a_marginal_score(self) -> None:
        verdict = _determine_verdict(
            macro={"macro_environment": "neutral"}, **self._NEUTRAL_TALLY_KWARGS
        )
        assert verdict == "HOLD"

    def test_favourable_macro_alone_can_tip_a_marginal_score_to_buy(self) -> None:
        """
        Same inputs as the neutral-macro baseline (score 0.40, HOLD) --
        only macro_environment changes, from "neutral" to "favourable"
        (+0.75). 0.40 + 0.75 = 1.15... not quite enough on its own, so
        this fixture nudges fundamental up by one point (score=7,
        contributing +0.80 instead of +0.40) to land the neutral-macro
        baseline at HOLD (0.80) and the favourable-macro score at
        exactly 1.55 -- BUY. Before this fix, macro_environment could
        not have produced this difference at all: both cases would have
        resolved to the same verdict as the "neutral" case.
        """
        kwargs = {**self._NEUTRAL_TALLY_KWARGS, "fundamental": {"score": 7}}
        baseline = _determine_verdict(macro={"macro_environment": "neutral"}, **kwargs)
        assert baseline == "HOLD"

        with_favourable_macro = _determine_verdict(macro=_MACRO_FAVOURABLE, **kwargs)
        assert with_favourable_macro == "BUY"

    def test_unfavourable_macro_alone_can_tip_a_marginal_score_to_sell(self) -> None:
        """Mirror image of the favourable-macro test, on the bearish side."""
        kwargs = {**self._NEUTRAL_TALLY_KWARGS, "fundamental": {"score": 3}}
        baseline = _determine_verdict(macro={"macro_environment": "neutral"}, **kwargs)
        assert baseline == "HOLD"

        with_unfavourable_macro = _determine_verdict(
            macro=_MACRO_UNFAVOURABLE, **kwargs
        )
        assert with_unfavourable_macro == "SELL"

    def test_missing_macro_output_defaults_to_neutral_zero_contribution(self) -> None:
        """
        A Macro Economist run that errored/produced no output must
        degrade to zero influence on the verdict -- the same safe-default
        pattern fund_score/tech_signal/valuation_verdict already use --
        not crash, and not silently favour either direction.
        """
        verdict_missing = _determine_verdict(macro={}, **self._NEUTRAL_TALLY_KWARGS)
        verdict_explicit_neutral = _determine_verdict(
            macro={"macro_environment": "neutral"}, **self._NEUTRAL_TALLY_KWARGS
        )
        assert verdict_missing == verdict_explicit_neutral == "HOLD"


# ---------------------------------------------------------------------------
# Tests: _data_completeness / _determine_verdict data-completeness scaling
# (bug #12, T-087) -- Section A's regression requirement: "a company with
# genuinely strong fundamentals + undervalued + positive sentiment + low
# risk produces BUY" AND missing research-agent data must not manufacture
# a structurally bearish verdict via an ungrounded Risk/Contrarian penalty.
# ---------------------------------------------------------------------------


class TestDataCompleteness:
    def test_full_data_is_complete(self) -> None:
        assert _data_completeness(
            _FUNDAMENTAL_STRONG, _TECHNICAL_BUY_STRONG, _VALUATION_UNDERVALUED
        ) == pytest.approx(1.0)

    def test_all_three_missing_is_zero(self) -> None:
        assert _data_completeness({}, {}, {}) == pytest.approx(0.0)

    def test_errored_agent_counts_as_incomplete(self) -> None:
        errored = {**_FUNDAMENTAL_STRONG, "error": "rate limited"}
        assert _data_completeness(
            errored, _TECHNICAL_BUY_STRONG, _VALUATION_UNDERVALUED
        ) == pytest.approx(2.0 / 3.0)

    def test_one_of_three_present_is_one_third(self) -> None:
        assert _data_completeness(_FUNDAMENTAL_STRONG, {}, {}) == pytest.approx(
            1.0 / 3.0
        )


class TestDetermineVerdictBuyReachability:
    def test_genuinely_strong_profile_produces_buy(self) -> None:
        """
        Section A's explicit regression requirement: strong fundamentals +
        undervalued + positive sentiment + low risk must produce BUY when
        the underlying data is actually present and genuinely bullish.
        """
        verdict = _determine_verdict(
            fundamental=_FUNDAMENTAL_STRONG,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro={},
            risk=_RISK_LOW,
            contrarian=_CONTRARIAN_MILD,
            valuation=_VALUATION_UNDERVALUED,
            critical_flags=[],
        )
        assert verdict == "BUY"

    def test_degraded_upstream_data_does_not_force_a_bearish_verdict(self) -> None:
        """
        Reproduces the Tata-Motors-memo failure chain directly: Fundamental,
        Technical, and Valuation all lack data (a cold-run yFinance 429,
        pre-hardening), while Risk Officer and Contrarian Investor still
        render a moderately bearish opinion (their mandate doesn't stop
        just because upstream data is missing). Pre-fix, their unscaled
        penalty (~-1.0 combined) had nothing bullish to offset it (every
        bullish input correctly defaults to a neutral zero for the same
        missing-data reason) and could push the score toward SELL/HOLD
        purely from data unavailability. Post-fix, the same Risk/Contrarian
        penalty is scaled by completeness=0.0 -- i.e. fully discounted, an
        evidence-backed committee treats "we don't know" as neutral, not
        bearish -- so the verdict is exactly HOLD (the score is 0.0).
        """
        verdict = _determine_verdict(
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={"risk_score": 6},
            contrarian={"bear_conviction": 6},
            valuation={},
            critical_flags=["Insufficient data availability"],
        )
        assert verdict == "HOLD"

    def test_degraded_data_with_real_bullish_signal_now_reaches_buy(self) -> None:
        """
        The precise regression this fix targets: with fundamental/
        technical/valuation all missing (completeness=0.0) and one
        genuinely bullish, ungated signal present (maximally positive
        sentiment, which does not depend on yFinance), the weighted tally
        is exactly 1.5 -- BUY -- because the Risk/Contrarian/critical-flags
        penalties are fully discounted by data completeness.

        Proof this is a real regression, not just an assertion: recomputing
        the SAME inputs through the pre-fix (unscaled) formula gives
        1.5 - (6-5)*0.35 - (6-1)*0.1 - 1*0.3 = 0.35 -- HOLD, not BUY. A
        single missing-data-driven "the committee looks skeptical" penalty
        was enough to block BUY even though nothing in it was actually
        evidence-backed. The completeness fix is what closes that gap.
        """
        verdict = _determine_verdict(
            fundamental={},
            technical={},
            sentiment={"sentiment_score": 1.0},
            macro={},
            risk={"risk_score": 6},
            contrarian={"bear_conviction": 6},
            valuation={},
            critical_flags=["Insufficient data availability"],
        )
        assert verdict == "BUY"

    def test_full_completeness_bearish_penalty_is_unchanged(self) -> None:
        """
        Regression guard in the other direction: when data completeness IS
        1.0 (the common case), the Risk/Contrarian penalty must be exactly
        as strong as before this fix -- completeness-scaling must not
        soften a genuinely well-supported bearish case.
        """
        verdict = _determine_verdict(
            fundamental=_FUNDAMENTAL_WEAK,
            technical=_TECHNICAL_SELL_STRONG,
            sentiment=_SENTIMENT_NEGATIVE,
            macro={},
            risk=_RISK_HIGH,
            contrarian=_CONTRARIAN_STRONG,
            valuation=_VALUATION_OVERVALUED,
            critical_flags=_RISK_HIGH["critical_flags"],
        )
        assert verdict == "SELL"


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

    def test_macro_direction_now_counts_toward_the_agreement_bonus(self) -> None:
        """
        Audit finding (Section C, unit 9): before this fix, ``macro`` was
        only ever used here to count toward ``error_count`` -- its
        directional view (favourable/unfavourable) never entered the
        fund/tech/sentiment/valuation "agreement" calculation that drives
        the +-2.0 conviction bonus/penalty. This test isolates exactly
        that: fundamental and technical both point bullish (+1 each) but
        sentiment and valuation are both neutral (0, excluded from the
        agreement calculation), so only 2 directions are on the board --
        one short of the `len(directions) >= 3` bonus threshold. Adding a
        favourable macro reading is the ONLY thing that supplies the 3rd
        agreeing direction and unlocks the +2.0 bonus; before this fix,
        macro could never do that.
        """
        fundamental_bullish = {"score": 8}  # fund_dir = +1
        technical_bullish = {"signal": "BUY"}  # tech_dir = +1
        sentiment_neutral = {"sentiment_score": 0.0}  # sent_dir = 0 (excluded)
        valuation_neutral = {
            "valuation_verdict": "fairly_valued"
        }  # val_dir = 0 (excluded)
        risk_neutral = {"risk_score": 5}
        contrarian_mild = {"bear_conviction": 1}

        conviction_with_neutral_macro = _score_conviction(
            fundamental_bullish,
            technical_bullish,
            sentiment_neutral,
            {
                "macro_environment": "neutral"
            },  # macro_dir = 0 -- only 2 directions total
            risk_neutral,
            contrarian_mild,
            valuation_neutral,
            verdict="BUY",
            debate_rounds_used=1,
        )
        conviction_with_favourable_macro = _score_conviction(
            fundamental_bullish,
            technical_bullish,
            sentiment_neutral,
            _MACRO_FAVOURABLE,  # macro_dir = +1 -- the 3rd agreeing direction
            risk_neutral,
            contrarian_mild,
            valuation_neutral,
            verdict="BUY",
            debate_rounds_used=1,
        )

        assert conviction_with_neutral_macro == 6  # 5.0 base + 1.0 (bear_conviction<=3)
        assert (
            conviction_with_favourable_macro == 8
        )  # + 2.0 agreement bonus, unlocked by macro

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
    """
    B1 fix: the user's selected analysis ``period`` is now the PRIMARY
    driver of the displayed holding period -- previously this function
    ignored ``period`` entirely, hardcoding "quarterly review (3 months)"
    for every HOLD and a flat "12 months" default for BUY/SELL regardless
    of what horizon the user actually selected.
    """

    def test_hold_reflects_the_selected_period(self) -> None:
        horizon = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="HOLD", period="3y"
        )
        assert "3 years" in horizon
        assert "quarter" in horizon.lower()

    def test_hold_on_a_short_period_no_longer_says_three_months(self) -> None:
        """The exact pre-fix bug: HOLD used to always say '(3 months)'
        even when the user selected a completely different period."""
        horizon = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="HOLD", period="1mo"
        )
        assert "1 month" in horizon
        assert "3 months" not in horizon

    def test_technically_driven_buy_reflects_the_selected_period(self) -> None:
        horizon = _determine_time_horizon(
            _TECHNICAL_BUY_STRONG, _VALUATION_FAIR, verdict="BUY", period="6mo"
        )
        assert "6 months" in horizon
        assert "technically driven" in horizon.lower()

    def test_high_margin_of_safety_buy_reflects_the_selected_period(self) -> None:
        weak_technical = {"signal": "BUY", "signal_strength": 4}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_UNDERVALUED, verdict="BUY", period="10y"
        )
        assert "10 years" in horizon
        assert "high margin of safety" in horizon.lower()

    def test_default_buy_case_is_exactly_the_period_label(self) -> None:
        weak_technical = {"signal": "HOLD", "signal_strength": 5}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_FAIR, verdict="BUY", period="1y"
        )
        assert horizon == "~1 year"

    def test_selecting_3y_yields_a_three_year_horizon(self) -> None:
        """Explicit B1 acceptance check named in the work order."""
        horizon = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="BUY", period="3y"
        )
        assert horizon == "~3 years"

    def test_selecting_1mo_yields_a_one_month_horizon(self) -> None:
        """Explicit B1 acceptance check named in the work order."""
        horizon = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="BUY", period="1mo"
        )
        assert horizon == "~1 month"

    @pytest.mark.parametrize(
        ("period", "expected_label"),
        [
            ("1mo", "~1 month"),
            ("3mo", "~3 months"),
            ("6mo", "~6 months"),
            ("1y", "~1 year"),
            ("3y", "~3 years"),
            ("5y", "~5 years"),
            ("10y", "~10 years"),
        ],
    )
    def test_every_supported_period_maps_to_its_own_label(
        self, period: str, expected_label: str
    ) -> None:
        """B1: confirm across all supported periods (default BUY case,
        where the label is returned unmodified)."""
        weak_technical = {"signal": "HOLD", "signal_strength": 5}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_FAIR, verdict="BUY", period=period
        )
        assert horizon == expected_label

    def test_unrecognised_period_falls_back_to_one_year(self) -> None:
        weak_technical = {"signal": "HOLD", "signal_strength": 5}
        horizon = _determine_time_horizon(
            weak_technical, _VALUATION_FAIR, verdict="BUY", period="2mo"
        )
        assert horizon == "~1 year"

    def test_verdict_never_overrides_the_periods_magnitude(self) -> None:
        """The period is the primary driver -- verdict/technicals only
        refine wording, they never substitute a different magnitude."""
        hold = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="HOLD", period="5y"
        )
        buy = _determine_time_horizon(
            _TECHNICAL_HOLD, _VALUATION_FAIR, verdict="BUY", period="5y"
        )
        assert "5 years" in hold
        assert "5 years" in buy


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
# Tests: B2 -- relative price target fallback (bug #8 tail, T-087)
#
# Once the DCF has no intrinsic value (e.g. Section A's missing-financials
# chain, or genuinely insufficient FCF history), the price target must
# fall back to a peer-multiple-based relative estimate rather than the
# flat "Not determined" placeholder -- and must never fabricate a number
# when no usable data exists at all.
# ---------------------------------------------------------------------------


class TestBuildRelativePriceTarget:
    def test_falls_back_to_pe_relative_estimate_when_intrinsic_missing(self) -> None:
        valuation = {
            "current_price": 1000.0,
            "pe_ratio": 15.0,
            "sector_avg_pe": 20.0,
        }
        result = _build_price_target(valuation, "12 months")
        assert result is not None
        # target = 1000 * (20 / 15) = 1333.33 -> rounds to 1,333
        assert "1,333" in result
        assert "relative estimate" in result
        assert "P/E" in result

    def test_falls_back_to_pb_when_pe_data_unavailable(self) -> None:
        valuation = {
            "current_price": 500.0,
            "pb_ratio": 2.0,
            "sector_avg_pb": 3.0,
        }
        result = _build_price_target(valuation, "12 months")
        assert result is not None
        # target = 500 * (3 / 2) = 750
        assert "750" in result
        assert "P/B" in result

    def test_pe_takes_priority_over_pb_when_both_available(self) -> None:
        valuation = {
            "current_price": 1000.0,
            "pe_ratio": 15.0,
            "sector_avg_pe": 20.0,
            "pb_ratio": 2.0,
            "sector_avg_pb": 10.0,  # would imply a wildly different target
        }
        result = _build_price_target(valuation, "12 months")
        assert result is not None
        assert "1,333" in result
        assert "P/E" in result

    def test_intrinsic_value_takes_priority_over_relative_fallback(self) -> None:
        valuation = {
            "intrinsic_value_per_share": 4500.0,
            "current_price": 1000.0,
            "pe_ratio": 15.0,
            "sector_avg_pe": 20.0,
        }
        result = _build_price_target(valuation, "12 months")
        assert result is not None
        assert "4,500" in result
        assert "relative estimate" not in result

    def test_never_fabricates_a_number_with_no_current_price(self) -> None:
        valuation = {"pe_ratio": 15.0, "sector_avg_pe": 20.0}
        assert _build_relative_price_target(valuation, "12 months") is None

    def test_never_fabricates_a_number_with_no_multiples_at_all(self) -> None:
        valuation = {"current_price": 1000.0}
        assert _build_relative_price_target(valuation, "12 months") is None

    def test_zero_or_negative_own_multiple_is_not_used(self) -> None:
        valuation = {
            "current_price": 1000.0,
            "pe_ratio": 0.0,
            "sector_avg_pe": 20.0,
            "pb_ratio": -1.0,
            "sector_avg_pb": 3.0,
        }
        assert _build_relative_price_target(valuation, "12 months") is None

    def test_end_to_end_through_build_price_target_returns_labelled_estimate(
        self,
    ) -> None:
        """Full B2 acceptance check: given a valuation dict shaped exactly
        like ValuationOutput.model_dump() with no DCF but real peer
        multiples, the memo-facing price target is populated, not 'Not
        determined'."""
        result = _build_price_target(_VALUATION_NO_DCF_WITH_PEERS, "12 months")
        assert result is not None
        assert result != "Not determined"


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

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_period_threads_through_to_time_horizon(
        self, mock_get_llm: MagicMock
    ) -> None:
        """B1: the period kwarg (defaults to '1y' when omitted) reaches
        _determine_time_horizon and shows up verbatim in the decision."""
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
            period="5y",
        )
        assert "5 years" in result.time_horizon

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_period_omitted_defaults_to_one_year(self, mock_get_llm: MagicMock) -> None:
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
        assert "1 year" in result.time_horizon


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
        period: str = "1y",
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
            "period": period,
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

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_selecting_3y_flows_through_to_decision_time_horizon(
        self, mock_get_llm: MagicMock
    ) -> None:
        """B1 end-to-end acceptance check: state["period"] set by the
        Planner from the user's AnalysisStartRequest flows all the way
        through to InvestmentDecision.time_horizon."""
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state(period="3y"))
        assert "3 years" in result["decision"]["time_horizon"]

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_selecting_1mo_flows_through_to_decision_time_horizon(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_portfolio_manager_decision(self._make_state(period="1mo"))
        assert "1 month" in result["decision"]["time_horizon"]

    @patch("backend.agents.portfolio_manager.get_llm")
    def test_missing_period_key_falls_back_to_one_year(
        self, mock_get_llm: MagicMock
    ) -> None:
        """A state dict predating B1 (no 'period' key at all) must not
        crash -- it falls back to the same '1y' default AnalysisStart
        Request itself uses."""
        mock_get_llm.return_value = _make_llm()
        state = self._make_state()
        del state["period"]
        result = run_portfolio_manager_decision(state)
        assert "1 year" in result["decision"]["time_horizon"]

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

    @patch("backend.agents.portfolio_manager._run_portfolio_manager_core")
    def test_unhandled_core_exception_degrades_to_hold(
        self, mock_core: MagicMock
    ) -> None:
        """
        Regression test for the "never raises" contract (T-074 audit finding
        F-A): a bug inside _run_portfolio_manager_core (e.g. a Pydantic
        construction error) must never propagate out of the LangGraph node --
        it must degrade to a HOLD/conviction=1 InvestmentDecision, matching
        every other agent's node-entry-point exception guard.
        """
        mock_core.side_effect = ValueError("boom: simulated core failure")
        result = run_portfolio_manager_decision(self._make_state())
        assert "decision" in result
        assert result["decision"].get("error") is not None
        assert "boom" in result["decision"]["error"]
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
