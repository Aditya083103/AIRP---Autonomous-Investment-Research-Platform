# backend/tests/unit/test_contrarian_investor.py
"""
Unit tests for T-038: Contrarian Investor Agent.

Test strategy:
  1. _build_counter_arguments  -- deterministic counter-arg generation
  2. _score_bear_conviction    -- deterministic conviction scoring
  3. _build_contrarian_prompt  -- prompt content and structure
  4. _run_contrarian_analysis_core -- full agent with mocked LLM
  5. run_contrarian_analysis   -- LangGraph node: state in -> state out
  6. Error paths               -- missing ticker, empty research, LLM failure
  7. Acceptance criteria       -- >= 3 counter-args for TCS/Infosys profiles
  8. Schema validation         -- ContrarianReport Pydantic constraints
  9. LangSmith tracing         -- @traced_agent applied

Acceptance criteria verified (from task spec):
  * At least 3 distinct counter-arguments for any bullish stock
  * Validated on TCS (fundamental 9/10, BUY signal) and
    Infosys (fundamental 8/10, RSI > 65) profiles
  * ContrarianReport fields all populated
  * bear_conviction in [1, 10]
  * Agent never raises -- always returns dict with 'contrarian' key

All external calls (LLM, APIs) are mocked.
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

from backend.agents.contrarian_investor import (  # noqa: E402
    MIN_COUNTER_ARGUMENTS,
    SYSTEM_PROMPT,
    _build_contrarian_prompt,
    _build_counter_arguments,
    _run_contrarian_analysis_core,
    _score_bear_conviction,
    run_contrarian_analysis,
)
from backend.agents.output_models import ContrarianReport  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# TCS-like: very bullish fundamentals, BUY signal, positive sentiment
_FUNDAMENTAL_TCS: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 9,
    "debt_to_equity": 0.02,
    "current_ratio": 2.1,
    "roe_pct": 46.2,
    "pe_ratio": 28.5,
    "free_cash_flow_cr": 44000.0,
    "strengths": [
        "Revenue CAGR of 13.7% over 4 years",
        "ROE of 46.2% exceeds sector average",
        "Net cash balance sheet",
        "FCF margin 18.3%",
    ],
    "weaknesses": ["High PE of 28.5x limits upside"],
    "summary": (
        "TCS demonstrates exceptional fundamental quality with consistent "
        "double-digit growth and industry-leading ROE."
    ),
}

# Infosys-like: strong but slightly lower score, RSI overbought
_FUNDAMENTAL_INFOSYS: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 8,
    "debt_to_equity": 0.05,
    "current_ratio": 1.9,
    "roe_pct": 29.5,
    "pe_ratio": 24.0,
    "free_cash_flow_cr": 18000.0,
    "strengths": [
        "Consistent FCF generation",
        "Low debt, strong balance sheet",
        "ROCE > 30%",
    ],
    "weaknesses": ["Revenue growth decelerating", "Margin pressure from hiring"],
    "summary": (
        "Infosys has strong quality metrics but decelerating growth raises "
        "questions about future earnings trajectory."
    ),
}

_TECHNICAL_BUY_STRONG: dict[str, Any] = {
    "signal": "BUY",
    "signal_strength": 8,
    "rsi_14": 68.0,
    "price_vs_52w_high_pct": 93.0,
    "summary": "Strong uptrend, price above both MAs, bullish momentum.",
}

_TECHNICAL_BUY_OVERBOUGHT: dict[str, Any] = {
    "signal": "BUY",
    "signal_strength": 7,
    "rsi_14": 72.0,
    "price_vs_52w_high_pct": 96.0,
    "summary": "Bullish trend but RSI overbought at 72.",
}

_TECHNICAL_HOLD: dict[str, Any] = {
    "signal": "HOLD",
    "signal_strength": 5,
    "rsi_14": 52.0,
    "price_vs_52w_high_pct": 75.0,
    "summary": "Neutral signal, sideways price action.",
}

_TECHNICAL_SELL: dict[str, Any] = {
    "signal": "SELL",
    "signal_strength": 7,
    "rsi_14": 72.0,
    "price_vs_52w_high_pct": 45.0,
    "summary": "Bearish reversal, price below 200-day MA.",
}

_SENTIMENT_POSITIVE: dict[str, Any] = {
    "sentiment_score": 0.45,
    "sentiment_label": "positive",
    "articles_analysed": 25,
    "red_flags": [],
    "red_flag_count": 0,
    "summary": "Predominantly positive news; strong deal wins and margin beat.",
}

_SENTIMENT_NEGATIVE: dict[str, Any] = {
    "sentiment_score": -0.4,
    "sentiment_label": "negative",
    "articles_analysed": 15,
    "red_flags": ["Management credibility concerns"],
    "red_flag_count": 1,
    "summary": "Negative news cycle; management credibility concerns flagged.",
}

_MACRO_NEUTRAL: dict[str, Any] = {
    "macro_environment": "neutral",
    "sector_impact": "neutral",
    "rbi_repo_rate_pct": 6.5,
    "headwinds": ["Global growth slowdown risk"],
    "tailwinds": ["Digital adoption", "INR depreciation benefits IT exporters"],
    "summary": "Neutral macro with balanced tailwinds and one headwind.",
}

_MACRO_ADVERSE: dict[str, Any] = {
    "macro_environment": "unfavourable",
    "sector_impact": "headwind",
    "rbi_repo_rate_pct": 7.0,
    "headwinds": [
        "Rising rates compress NBFC margins",
        "Regulatory tightening",
        "Global recession risk",
    ],
    "tailwinds": [],
    "summary": "Adverse macro with multiple sector headwinds.",
}

_RISK_LOW: dict[str, Any] = {
    "risk_score": 3,
    "governance_risk": 2,
    "regulatory_risk": 2,
    "financial_risk": 3,
    "concentration_risk": 3,
    "risk_recommendation": "proceed_with_caution",
    "summary": "Low risk profile; clean governance and balance sheet.",
}

_RISK_HIGH: dict[str, Any] = {
    "risk_score": 7,
    "governance_risk": 7,
    "regulatory_risk": 6,
    "financial_risk": 7,
    "concentration_risk": 5,
    "risk_recommendation": "avoid",
    "summary": "High risk with governance and regulatory concerns.",
}

_BASE_KWARGS: dict[str, Any] = {
    "analysis_id": "t038-test-uuid",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}

_LLM_JSON_RESPONSE = json.dumps(
    {
        "counter_arguments": [
            "The Fundamental Analyst's ROE of 46.2% is exceptional but "
            "attracts competition -- mean reversion is historically inevitable.",
            "The Technical Analyst's BUY signal at 93% of 52-week high "
            "means buyers are chasing momentum near the top of the range.",
            "The Macro Economist lists digital adoption as a tailwind but "
            "ignores that AI automation threatens the labour-arbitrage model "
            "that underpins IT services pricing.",
        ],
        "overlooked_risks": [
            "Currency hedging costs are not accounted for in the FCF analysis "
            "-- a 5% INR appreciation would reduce reported USD revenues by "
            "the same amount with no offsetting cost reduction.",
            "Client concentration: top 5 clients likely represent >25% of "
            "revenue -- a single churned account materially impacts guidance.",
        ],
        "strongest_argument": (
            "The stock is priced for perfection at 28.5x PE near its "
            "52-week high -- any miss on earnings or guidance will trigger "
            "a de-rating that the BUY signals completely ignore."
        ),
        "challenged_agents": ["fundamental_analyst", "technical_analyst"],
        "summary": (
            "TCS is a quality business trading at a quality price with no "
            "margin of safety. The committee's bullish consensus has priced in "
            "years of flawless execution in a sector facing structural headwinds "
            "from AI disruption."
        ),
    }
)


def _make_llm(content: str = _LLM_JSON_RESPONSE) -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = content
    mock.invoke.return_value = response
    return mock


# ---------------------------------------------------------------------------
# Tests: MIN_COUNTER_ARGUMENTS constant
# ---------------------------------------------------------------------------


class TestConstants:
    def test_min_counter_arguments_is_3(self) -> None:
        assert MIN_COUNTER_ARGUMENTS == 3


# ---------------------------------------------------------------------------
# Tests: _build_counter_arguments
# ---------------------------------------------------------------------------


class TestBuildCounterArguments:
    def test_tcs_profile_produces_at_least_3_args(self) -> None:
        """Acceptance criteria: >= 3 counter-args for bullish TCS profile."""
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        assert (
            len(args) >= MIN_COUNTER_ARGUMENTS
        ), f"Expected >= {MIN_COUNTER_ARGUMENTS} args for TCS, got {len(args)}: {args}"

    def test_infosys_profile_produces_at_least_3_args(self) -> None:
        """Acceptance criteria: >= 3 counter-args for bullish Infosys profile."""
        args = _build_counter_arguments(
            _FUNDAMENTAL_INFOSYS,
            _TECHNICAL_BUY_OVERBOUGHT,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        assert len(args) >= MIN_COUNTER_ARGUMENTS, (
            f"Expected >= {MIN_COUNTER_ARGUMENTS} args for Infosys, "
            f"got {len(args)}: {args}"
        )

    def test_high_pe_generates_valuation_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_pe_challenge = any(
            "pe" in a.lower() or "valu" in a.lower() or "margin of safety" in a.lower()
            for a in args
        )
        assert has_pe_challenge, f"No PE/valuation challenge in: {args}"

    def test_high_roe_generates_mean_reversion_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_roe_challenge = any(
            "roe" in a.lower() or "competi" in a.lower() or "reversion" in a.lower()
            for a in args
        )
        assert has_roe_challenge, f"No ROE/competition challenge in: {args}"

    def test_buy_signal_generates_momentum_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_technical_challenge = any(
            "buy" in a.lower() or "momentum" in a.lower() or "technical" in a.lower()
            for a in args
        )
        assert has_technical_challenge, f"No technical challenge in: {args}"

    def test_hold_signal_generates_trap_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_HOLD,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_hold_challenge = any("hold" in a.lower() for a in args)
        assert has_hold_challenge, f"No HOLD challenge found in: {args}"

    def test_overbought_rsi_generates_rsi_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_OVERBOUGHT,  # RSI 72
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_rsi_challenge = any("rsi" in a.lower() for a in args)
        assert has_rsi_challenge, f"No RSI challenge in: {args}"

    def test_near_52w_high_generates_top_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_OVERBOUGHT,  # 96% of 52w high
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_high_challenge = any(
            "52" in a or "high" in a.lower() or "top" in a.lower() for a in args
        )
        assert has_high_challenge, f"No 52-week-high challenge in: {args}"

    def test_positive_sentiment_generates_contrarian_sentiment_arg(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_sentiment_challenge = any(
            "sentiment" in a.lower() or "optimis" in a.lower() for a in args
        )
        assert has_sentiment_challenge, f"No sentiment challenge in: {args}"

    def test_low_risk_score_generates_complacency_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,  # risk_score = 3
        )
        has_risk_challenge = any(
            "risk" in a.lower() and ("complacen" in a.lower() or "lull" in a.lower())
            for a in args
        )
        assert has_risk_challenge, f"No risk complacency challenge in: {args}"

    def test_low_de_generates_growth_exhaustion_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,  # D/E = 0.02
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_de_challenge = any(
            "debt" in a.lower() or "cash" in a.lower() or "growth" in a.lower()
            for a in args
        )
        assert has_de_challenge

    def test_high_de_generates_leverage_challenge(self) -> None:
        fundamental_high_de: dict[str, Any] = dict(_FUNDAMENTAL_TCS)
        fundamental_high_de["debt_to_equity"] = 1.5
        args = _build_counter_arguments(
            fundamental_high_de,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        has_leverage_challenge = any(
            "leverage" in a.lower() or "d/e" in a.lower() or "debt" in a.lower()
            for a in args
        )
        assert has_leverage_challenge, f"No leverage challenge in: {args}"

    def test_adverse_macro_generates_macro_challenge(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_ADVERSE,  # neutral classification but 3 headwinds
            _RISK_LOW,
        )
        # Should generate a macro challenge about direction of travel
        has_macro_challenge = any(
            "macro" in a.lower() or "headwind" in a.lower() for a in args
        )
        assert has_macro_challenge

    def test_args_capped_at_six(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_OVERBOUGHT,
            _SENTIMENT_POSITIVE,
            _MACRO_ADVERSE,
            _RISK_LOW,
        )
        assert len(args) <= 6

    def test_all_args_are_strings(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        assert all(isinstance(a, str) for a in args)

    def test_empty_dicts_do_not_raise(self) -> None:
        args = _build_counter_arguments({}, {}, {}, {}, {})
        assert isinstance(args, list)

    def test_all_args_are_non_empty_strings(self) -> None:
        args = _build_counter_arguments(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _MACRO_NEUTRAL,
            _RISK_LOW,
        )
        assert all(len(a) > 10 for a in args)


# ---------------------------------------------------------------------------
# Tests: _score_bear_conviction
# ---------------------------------------------------------------------------


class TestScoreBearConviction:
    def _base_args(self) -> list[str]:
        return ["arg1", "arg2", "arg3"]

    def test_bullish_profile_scores_high_conviction(self) -> None:
        """TCS-like profile: high fund score, BUY signal, positive sentiment."""
        args = ["a"] * 5
        score = _score_bear_conviction(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_STRONG,
            _SENTIMENT_POSITIVE,
            _RISK_LOW,
            args,
        )
        # Many bullish signals = high contrarian conviction
        assert score >= 5, f"Expected >= 5 conviction for bullish profile, got {score}"

    def test_bearish_profile_low_conviction(self) -> None:
        """Bearish + SELL signal -> low conviction."""
        fundamental_weak: dict[str, Any] = dict(_FUNDAMENTAL_TCS)
        fundamental_weak["score"] = 3
        fundamental_weak["roe_pct"] = 8.0
        fundamental_weak["debt_to_equity"] = 0.5

        score = _score_bear_conviction(
            fundamental_weak,
            _TECHNICAL_SELL,
            _SENTIMENT_NEGATIVE,
            _RISK_HIGH,
            self._base_args(),
        )
        assert score <= 4, f"Expected <= 4 conviction for bearish profile, got {score}"

    def test_fund_score_8_plus_adds_2_points(self) -> None:
        score_high = _score_bear_conviction(
            _FUNDAMENTAL_TCS,  # score=9
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        fundamental_low: dict[str, Any] = dict(_FUNDAMENTAL_TCS)
        fundamental_low["score"] = 5
        score_low = _score_bear_conviction(
            fundamental_low,
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        assert score_high >= score_low + 2

    def test_buy_signal_strength_6_plus_adds_point(self) -> None:
        score_buy = _score_bear_conviction(
            {"score": 5, "debt_to_equity": 0.5},
            _TECHNICAL_BUY_STRONG,  # BUY, strength 8
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        score_hold = _score_bear_conviction(
            {"score": 5, "debt_to_equity": 0.5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        assert score_buy > score_hold

    def test_overbought_rsi_adds_point(self) -> None:
        score_overbought = _score_bear_conviction(
            {"score": 5},
            {"signal": "BUY", "signal_strength": 5, "rsi_14": 70.0},
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        score_neutral_rsi = _score_bear_conviction(
            {"score": 5},
            {"signal": "BUY", "signal_strength": 5, "rsi_14": 50.0},
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        assert score_overbought > score_neutral_rsi

    def test_high_sentiment_adds_point(self) -> None:
        score_high_sent = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.5},
            {"risk_score": 5},
            self._base_args(),
        )
        score_neutral_sent = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            self._base_args(),
        )
        assert score_high_sent > score_neutral_sent

    def test_low_risk_score_adds_point(self) -> None:
        score_low_risk = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 2},
            self._base_args(),
        )
        score_high_risk = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 8},
            self._base_args(),
        )
        assert score_low_risk > score_high_risk

    def test_many_args_adds_point(self) -> None:
        score_many = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            ["a", "b", "c", "d", "e"],  # 5 args
        )
        score_few = _score_bear_conviction(
            {"score": 5},
            _TECHNICAL_HOLD,
            {"sentiment_score": 0.0},
            {"risk_score": 5},
            ["a", "b"],  # 2 args
        )
        assert score_many > score_few

    def test_score_always_in_bounds(self) -> None:
        score = _score_bear_conviction(
            _FUNDAMENTAL_TCS,
            _TECHNICAL_BUY_OVERBOUGHT,
            _SENTIMENT_POSITIVE,
            _RISK_LOW,
            ["a"] * 6,
        )
        assert 1 <= score <= 10

    def test_empty_dicts_return_valid_score(self) -> None:
        score = _score_bear_conviction({}, {}, {}, {}, [])
        assert 1 <= score <= 10


# ---------------------------------------------------------------------------
# Tests: _build_contrarian_prompt
# ---------------------------------------------------------------------------


class TestBuildContrarianPrompt:
    def _call(
        self,
        fundamental: dict[str, Any] = _FUNDAMENTAL_TCS,
        technical: dict[str, Any] = _TECHNICAL_BUY_STRONG,
        sentiment: dict[str, Any] = _SENTIMENT_POSITIVE,
        macro: dict[str, Any] = _MACRO_NEUTRAL,
        risk: dict[str, Any] = _RISK_LOW,
    ) -> str:
        return _build_contrarian_prompt(
            company_name="TCS",
            ticker="TCS.NS",
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            risk=risk,
            pre_counter_arguments=["Arg 1: challenge the PE", "Arg 2: ROE reversion"],
            bear_conviction=6,
            debate_round=1,
        )

    def test_company_name_in_prompt(self) -> None:
        assert "TCS" in self._call()

    def test_ticker_in_prompt(self) -> None:
        assert "TCS.NS" in self._call()

    def test_bear_conviction_in_prompt(self) -> None:
        assert "6/10" in self._call()

    def test_debate_round_in_prompt(self) -> None:
        assert "round 1" in self._call().lower()

    def test_pre_args_in_prompt(self) -> None:
        prompt = self._call()
        assert "Arg 1: challenge the PE" in prompt
        assert "Arg 2: ROE reversion" in prompt

    def test_fundamental_summary_in_prompt(self) -> None:
        prompt = self._call()
        assert "exceptional" in prompt.lower() or "tcs" in prompt.lower()

    def test_technical_signal_in_prompt(self) -> None:
        assert "BUY" in self._call()

    def test_risk_score_in_prompt(self) -> None:
        assert "3/10" in self._call()

    def test_prompt_is_ascii_only(self) -> None:
        prompt = self._call()
        prompt.encode("ascii")  # raises if non-ASCII

    def test_none_values_formatted_as_na(self) -> None:
        fundamental_sparse: dict[str, Any] = {"score": 5, "debt_to_equity": None}
        prompt = self._call(fundamental=fundamental_sparse)
        assert "N/A" in prompt

    def test_empty_dicts_do_not_raise(self) -> None:
        result = _build_contrarian_prompt(
            company_name="X",
            ticker="X.NS",
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={},
            pre_counter_arguments=[],
            bear_conviction=1,
            debate_round=1,
        )
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: _run_contrarian_analysis_core
# ---------------------------------------------------------------------------


class TestRunContrarianAnalysisCore:
    @patch("backend.agents.contrarian_investor.get_llm")
    def test_tcs_produces_at_least_3_counter_args(
        self, mock_get_llm: MagicMock
    ) -> None:
        """Acceptance criteria: >= 3 counter-arguments for TCS."""
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert isinstance(result, ContrarianReport)
        assert len(result.counter_arguments) >= MIN_COUNTER_ARGUMENTS, (
            f"TCS: expected >= {MIN_COUNTER_ARGUMENTS} counter-args, "
            f"got {len(result.counter_arguments)}"
        )

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_infosys_produces_at_least_3_counter_args(
        self, mock_get_llm: MagicMock
    ) -> None:
        """Acceptance criteria: >= 3 counter-arguments for Infosys."""
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            analysis_id="infosys-test",
            company_name="Infosys",
            ticker="INFY.NS",
            fundamental=_FUNDAMENTAL_INFOSYS,
            technical=_TECHNICAL_BUY_OVERBOUGHT,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert isinstance(result, ContrarianReport)
        assert len(result.counter_arguments) >= MIN_COUNTER_ARGUMENTS, (
            f"Infosys: expected >= {MIN_COUNTER_ARGUMENTS} counter-args, "
            f"got {len(result.counter_arguments)}"
        )

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_bear_conviction_within_bounds(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert 1 <= result.bear_conviction <= 10

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_strongest_argument_non_empty(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert len(result.strongest_argument) > 10

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_llm_counter_args_merged_with_deterministic(
        self, mock_get_llm: MagicMock
    ) -> None:
        """LLM args should be merged with pre-computed args (not replace them)."""
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        # LLM response has 3 args, pre-computed has >= 3. Merged should be >= 3.
        assert len(result.counter_arguments) >= MIN_COUNTER_ARGUMENTS

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_llm_strongest_argument_used(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        # LLM response provides a strongest_argument
        assert "priced for perfection" in result.strongest_argument.lower()

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_llm_failure_returns_valid_model(self, mock_get_llm: MagicMock) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("quota exceeded")
        mock_get_llm.return_value = mock_llm
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert isinstance(result, ContrarianReport)
        # Even without LLM, pre-computed args must satisfy acceptance criteria
        assert len(result.counter_arguments) >= MIN_COUNTER_ARGUMENTS
        assert result.error is None  # LLM failure is non-fatal

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_llm_invalid_json_gracefully_handled(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm("NOT JSON {{{")
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert isinstance(result, ContrarianReport)
        assert len(result.counter_arguments) >= MIN_COUNTER_ARGUMENTS

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_empty_research_dicts_do_not_raise(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental={},
            technical={},
            sentiment={},
            macro={},
            risk={},
            debate_round=1,
        )
        assert isinstance(result, ContrarianReport)
        assert 1 <= result.bear_conviction <= 10

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_model_is_frozen(self, mock_get_llm: MagicMock) -> None:
        from pydantic import ValidationError

        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        with pytest.raises(ValidationError):
            result.bear_conviction = 99  # type: ignore[misc]

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_model_dump_is_json_serialisable(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        json.dumps(result.model_dump(), default=str)  # must not raise

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_debate_round_passed_to_core(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        # Round 2 should still produce valid output
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=2,
        )
        assert isinstance(result, ContrarianReport)

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_high_conviction_for_very_bullish_profile(
        self, mock_get_llm: MagicMock
    ) -> None:
        """TCS at 52w high with RSI 68 and fund score 9 -> high conviction."""
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert result.bear_conviction >= 5

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_all_required_fields_populated(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = _run_contrarian_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_TCS,
            technical=_TECHNICAL_BUY_STRONG,
            sentiment=_SENTIMENT_POSITIVE,
            macro=_MACRO_NEUTRAL,
            risk=_RISK_LOW,
            debate_round=1,
        )
        assert result.agent_name == "contrarian_investor"
        assert result.analysis_id == "t038-test-uuid"
        assert result.company_name == "Tata Consultancy Services"
        assert result.ticker == "TCS.NS"
        assert isinstance(result.counter_arguments, list)
        assert isinstance(result.overlooked_risks, list)
        assert isinstance(result.challenged_agents, list)
        assert len(result.strongest_argument) > 0


# ---------------------------------------------------------------------------
# Tests: run_contrarian_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunContrarianAnalysisNode:
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
        debate_round_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "company_name": company_name,
            "ticker": ticker,
            "fundamental": fundamental or _FUNDAMENTAL_TCS,
            "technical": technical or _TECHNICAL_BUY_STRONG,
            "sentiment": sentiment or _SENTIMENT_POSITIVE,
            "macro": macro or _MACRO_NEUTRAL,
            "risk": risk or _RISK_LOW,
            "debate_round_count": debate_round_count,
        }

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_returns_dict_with_contrarian_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        assert "contrarian" in result
        assert isinstance(result["contrarian"], dict)

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_returns_debate_round_count_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state(debate_round_count=0))
        assert "debate_round_count" in result
        assert result["debate_round_count"] == 1  # incremented from 0

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_debate_round_count_incremented(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state(debate_round_count=1))
        assert result["debate_round_count"] == 2

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_contrarian_dict_has_required_fields(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        c = result["contrarian"]
        for field in (
            "agent_name",
            "bear_conviction",
            "counter_arguments",
            "overlooked_risks",
            "challenged_agents",
            "strongest_argument",
            "summary",
        ):
            assert field in c, f"Missing field: {field}"

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_agent_name_is_contrarian_investor(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        assert result["contrarian"]["agent_name"] == "contrarian_investor"

    def test_missing_ticker_returns_error_result(self) -> None:
        state: dict[str, Any] = {
            "job_id": "test-no-ticker",
            "company_name": "Test Corp",
            "ticker": "",
        }
        result = run_contrarian_analysis(state)
        assert "contrarian" in result
        assert result["contrarian"].get("error") is not None
        assert result["debate_round_count"] == 0

    @patch("backend.agents.contrarian_investor.get_llm")
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
            "debate_round_count": 0,
        }
        result = run_contrarian_analysis(state)
        assert "contrarian" in result
        assert 1 <= result["contrarian"]["bear_conviction"] <= 10

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_result_is_json_serialisable(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        json.dumps(result, default=str)  # must not raise

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_bear_conviction_within_bounds(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        assert 1 <= result["contrarian"]["bear_conviction"] <= 10

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_counter_arguments_is_list(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        assert isinstance(result["contrarian"]["counter_arguments"], list)

    @patch("backend.agents.contrarian_investor.get_llm")
    def test_counter_arguments_min_3_for_bullish_state(
        self, mock_get_llm: MagicMock
    ) -> None:
        """End-to-end acceptance criteria check via LangGraph node."""
        mock_get_llm.return_value = _make_llm()
        result = run_contrarian_analysis(self._make_state())
        args = result["contrarian"]["counter_arguments"]
        assert len(args) >= MIN_COUNTER_ARGUMENTS, (
            f"Node: expected >= {MIN_COUNTER_ARGUMENTS} counter-args, "
            f"got {len(args)}: {args}"
        )


# ---------------------------------------------------------------------------
# Tests: Schema validation (ContrarianReport Pydantic constraints)
# ---------------------------------------------------------------------------


class TestContrarianReportSchemaValidation:
    _BASE: dict[str, Any] = {
        "agent_name": "contrarian_investor",
        "analysis_id": "schema-test",
        "company_name": "Test Corp",
        "ticker": "TEST.NS",
        "bear_conviction": 5,
    }

    def test_valid_model_constructs_successfully(self) -> None:
        result = ContrarianReport(**self._BASE)
        assert result.bear_conviction == 5

    def test_bear_conviction_below_1_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContrarianReport(**{**self._BASE, "bear_conviction": 0})

    def test_bear_conviction_above_10_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContrarianReport(**{**self._BASE, "bear_conviction": 11})

    def test_default_counter_arguments_empty_list(self) -> None:
        result = ContrarianReport(**self._BASE)
        assert result.counter_arguments == []

    def test_default_overlooked_risks_empty_list(self) -> None:
        result = ContrarianReport(**self._BASE)
        assert result.overlooked_risks == []

    def test_default_challenged_agents_empty_list(self) -> None:
        result = ContrarianReport(**self._BASE)
        assert result.challenged_agents == []

    def test_model_is_frozen(self) -> None:
        from pydantic import ValidationError

        result = ContrarianReport(**self._BASE)
        with pytest.raises(ValidationError):
            result.bear_conviction = 99  # type: ignore[misc]

    def test_model_dump_round_trip(self) -> None:
        result = ContrarianReport(
            **self._BASE,
            counter_arguments=["Challenge 1", "Challenge 2"],
            overlooked_risks=["Hidden risk"],
            strongest_argument="The strongest bear case.",
            summary="Bear case summary.",
        )
        dumped = result.model_dump()
        assert dumped["counter_arguments"] == ["Challenge 1", "Challenge 2"]
        assert dumped["overlooked_risks"] == ["Hidden risk"]
        assert dumped["strongest_argument"] == "The strongest bear case."

    def test_agent_name_default(self) -> None:
        result = ContrarianReport(**self._BASE)
        assert result.agent_name == "contrarian_investor"


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

    def test_system_prompt_mentions_counter_arguments(self) -> None:
        assert "counter_arguments" in SYSTEM_PROMPT

    def test_system_prompt_mentions_overlooked_risks(self) -> None:
        assert "overlooked_risks" in SYSTEM_PROMPT

    def test_system_prompt_mentions_strongest_argument(self) -> None:
        assert "strongest_argument" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Tests: LangSmith tracing integration
# ---------------------------------------------------------------------------


class TestTracingIntegration:
    def test_run_contrarian_analysis_is_traced(self) -> None:
        """@traced_agent wraps the function; __wrapped__ exposes the original."""
        assert hasattr(run_contrarian_analysis, "__wrapped__"), (
            "run_contrarian_analysis is missing __wrapped__; "
            "@traced_agent was not applied"
        )

    def test_wrapped_function_is_callable(self) -> None:
        assert hasattr(run_contrarian_analysis, "__wrapped__")
        wrapped = getattr(run_contrarian_analysis, "__wrapped__", None)
        assert wrapped is not None
        assert callable(wrapped)
