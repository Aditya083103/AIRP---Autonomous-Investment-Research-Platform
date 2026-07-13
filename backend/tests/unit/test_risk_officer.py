# backend/tests/unit/test_risk_officer.py
"""
Unit tests for T-037: Risk Officer Agent.

Test strategy:
  1. _collect_all_text        -- flattens all research dicts into lowercase str
  2. _extract_sentinel_flags  -- keyword detection on combined research text
  3. _score_risk              -- deterministic sub-score and composite logic
  4. _determine_concentration_flags -- concrete concentration risk extraction
  5. _determine_risk_recommendation -- band mapping risk_score -> recommendation
  6. _build_risk_prompt       -- prompt structure and content verification
  7. _run_risk_analysis_core  -- full agent with mocked LLM; various inputs
  8. run_risk_analysis        -- LangGraph node: state in -> state out
  9. Error paths              -- missing ticker, empty research, LLM failure
 10. Known-risky company      -- agent correctly flags SEBI/fraud keywords
 11. Clean company            -- agent returns low risk_score for clean data
 12. Schema validation        -- RiskAnalysis Pydantic constraints enforced

Acceptance criteria verified:
  * Agent correctly flags known-risky companies (SEBI, fraud, high D/E)
  * Outputs structured RiskAnalysis with all required fields
  * risk_score in [1, 10]; sub-scores in [1, 10]
  * Agent never raises -- always returns dict with 'risk' key
  * LangSmith trace active via @traced_agent (checked via __wrapped__)

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

from backend.agents.output_models import RiskAnalysis  # noqa: E402
from backend.agents.risk_officer import (  # noqa: E402
    SYSTEM_PROMPT,
    _build_risk_prompt,
    _collect_all_text,
    _determine_concentration_flags,
    _determine_risk_recommendation,
    _extract_sentinel_flags,
    _run_risk_analysis_core,
    _score_risk,
    run_risk_analysis,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# Healthy TCS-like fundamental data
_FUNDAMENTAL_GOOD: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "analysis_id": "test-001",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "score": 9,
    "debt_to_equity": 0.02,
    "current_ratio": 2.1,
    "roe_pct": 46.2,
    "free_cash_flow_cr": 44000.0,
    "strengths": ["Strong FCF generation", "Net cash position"],
    "weaknesses": ["High PE ratio limits upside"],
    "summary": (
        "TCS demonstrates excellent fundamental quality with strong FCF and "
        "near-zero leverage."
    ),
}

# Risky fundamental data: high leverage, weak FCF
_FUNDAMENTAL_RISKY: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "analysis_id": "test-001",
    "company_name": "Risky Corp",
    "ticker": "RISKY.NS",
    "score": 3,
    "debt_to_equity": 2.5,
    "current_ratio": 0.8,
    "roe_pct": 4.0,
    "free_cash_flow_cr": -500.0,
    "strengths": [],
    "weaknesses": [
        "FCF negative for second consecutive year",
        "Debt/equity of 2.5x -- overleveraged",
    ],
    "summary": "Risky Corp has weak fundamentals with high leverage and negative FCF.",
}

_TECHNICAL_BULLISH: dict[str, Any] = {
    "signal": "BUY",
    "signal_strength": 7,
    "rsi_14": 55.0,
    "price_vs_52w_high_pct": 92.0,
    "summary": "Strong uptrend with price above both moving averages.",
}

_TECHNICAL_BEARISH: dict[str, Any] = {
    "signal": "SELL",
    "signal_strength": 8,
    "rsi_14": 72.0,
    "price_vs_52w_high_pct": 45.0,
    "summary": "Price momentum has reversed with overbought RSI.",
}

_SENTIMENT_CLEAN: dict[str, Any] = {
    "sentiment_score": 0.35,
    "sentiment_label": "positive",
    "articles_analysed": 20,
    "red_flags": [],
    "red_flag_count": 0,
    "summary": "Predominantly positive news coverage over the last 30 days.",
}

_SENTIMENT_RISKY: dict[str, Any] = {
    "sentiment_score": -0.5,
    "sentiment_label": "very_negative",
    "articles_analysed": 15,
    "red_flags": [
        "SEBI investigation into alleged insider trading",
        "CEO faces fraud probe",
        "Audit qualification on revenue recognition",
    ],
    "red_flag_count": 3,
    "summary": (
        "Very negative news coverage with regulatory and governance red flags."
    ),
}

_MACRO_NEUTRAL: dict[str, Any] = {
    "macro_environment": "neutral",
    "sector_impact": "neutral",
    "rbi_repo_rate_pct": 6.5,
    "headwinds": ["Global growth slowdown"],
    "tailwinds": ["Digital adoption acceleration"],
    "summary": "Neutral macro with balanced sector tailwinds and headwinds.",
}

_MACRO_ADVERSE: dict[str, Any] = {
    "macro_environment": "unfavourable",
    "sector_impact": "headwind",
    "rbi_repo_rate_pct": 7.0,
    "headwinds": [
        "Rising interest rates hurt NBFC margins",
        "Regulatory tightening on lending norms",
        "Global recession risk weighing on exports",
    ],
    "tailwinds": [],
    "summary": "Adverse macro environment with multiple sector headwinds.",
}

_BASE_KWARGS: dict[str, Any] = {
    "analysis_id": "t037-test-uuid",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
}

_LLM_JSON_CLEAN = json.dumps(
    {
        "governance_flags": [],
        "regulatory_risks": [],
        "fraud_indicators": [],
        "concentration_risks": [],
        "risk_recommendation": "proceed_with_caution",
        "summary": (
            "TCS presents a low-risk investment profile with strong governance "
            "and clean regulatory history. No material red flags identified across "
            "fundamental, sentiment, or macro dimensions."
        ),
    }
)

_LLM_JSON_RISKY = json.dumps(
    {
        "governance_flags": [
            "Management credibility severely damaged by CEO fraud probe"
        ],
        "regulatory_risks": [
            "Active SEBI investigation into insider trading -- outcome uncertain"
        ],
        "fraud_indicators": [
            "Audit qualification on revenue recognition is a serious red flag"
        ],
        "concentration_risks": [
            "Highly leveraged balance sheet creates refinancing risk in rising rate env"
        ],
        "risk_recommendation": "avoid",
        "summary": (
            "Risky Corp presents an extremely high-risk profile with active SEBI "
            "investigation, CEO fraud probe, and dangerous leverage at 2.5x D/E. "
            "Portfolio Manager should avoid until regulatory cloud clears."
        ),
    }
)


def _make_llm(content: str) -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = content
    mock.invoke.return_value = response
    return mock


# ---------------------------------------------------------------------------
# Tests: _collect_all_text
# ---------------------------------------------------------------------------


class TestCollectAllText:
    def test_flattens_string_fields(self) -> None:
        result = _collect_all_text(
            {"summary": "Strong revenue growth"},
            {"summary": "Bullish technical"},
            {"summary": "Positive news"},
            {"summary": "Neutral macro"},
        )
        assert "strong revenue growth" in result
        assert "bullish technical" in result
        assert "positive news" in result
        assert "neutral macro" in result

    def test_flattens_list_fields(self) -> None:
        result = _collect_all_text(
            {"weaknesses": ["High debt", "Weak FCF"]},
            {},
            {"red_flags": ["SEBI notice issued"]},
            {"headwinds": ["Rising rates"]},
        )
        assert "high debt" in result
        assert "sebi notice issued" in result
        assert "rising rates" in result

    def test_ignores_non_string_values(self) -> None:
        result = _collect_all_text(
            {"score": 8, "debt_to_equity": 0.5, "summary": "clean"},
            {},
            {},
            {},
        )
        assert "clean" in result
        # Numbers should not cause errors
        assert isinstance(result, str)

    def test_empty_dicts_produce_empty_string(self) -> None:
        result = _collect_all_text({}, {}, {}, {})
        assert result == "" or result.strip() == ""

    def test_all_lowercase(self) -> None:
        result = _collect_all_text(
            {"summary": "UPPER CASE Summary"},
            {},
            {},
            {},
        )
        assert result == result.lower()


# ---------------------------------------------------------------------------
# Tests: _extract_sentinel_flags
# ---------------------------------------------------------------------------


class TestExtractSentinelFlags:
    def test_inherits_sentiment_red_flags_as_governance(self) -> None:
        sentiment = {"red_flags": ["Promoter pledging of 60% holdings"]}
        flags = _extract_sentinel_flags("", sentiment)
        # Should appear in governance_flags (governance keyword: 'pledge')
        gov = flags["governance_flags"]
        assert len(gov) >= 1
        assert "pledging" in gov[0].lower() or "pledge" in gov[0].lower()

    def test_sebi_red_flag_classified_as_regulatory(self) -> None:
        sentiment = {"red_flags": ["SEBI investigation ongoing"]}
        flags = _extract_sentinel_flags("sebi investigation ongoing", sentiment)
        reg = flags["regulatory_risks"]
        # Should appear either from sentiment or keyword scan
        assert len(reg) >= 1

    def test_fraud_keyword_in_text_creates_fraud_flag(self) -> None:
        all_text = "company faces allegations of fraud and embezzlement"
        flags = _extract_sentinel_flags(all_text, {})
        assert len(flags["fraud_indicators"]) >= 1

    def test_regulatory_keyword_detection(self) -> None:
        all_text = "sebi has issued a notice to the company"
        flags = _extract_sentinel_flags(all_text, {})
        assert len(flags["regulatory_risks"]) >= 1

    def test_governance_keyword_detection(self) -> None:
        all_text = "auditor resignation raises concerns about governance"
        flags = _extract_sentinel_flags(all_text, {})
        assert len(flags["governance_flags"]) >= 1

    def test_clean_text_produces_empty_flags(self) -> None:
        flags = _extract_sentinel_flags(
            "strong revenue growth and healthy cash flows", {}
        )
        assert flags["fraud_indicators"] == []
        assert flags["regulatory_risks"] == []
        assert flags["governance_flags"] == []

    def test_flags_capped_at_five(self) -> None:
        # Generate text with many governance keyword hits
        all_text = (
            "promoter pledge auditor resignation director resign "
            "related party tunnelling preferential allotment audit qualification "
            "rights issue dilution board reconstitution"
        )
        flags = _extract_sentinel_flags(all_text, {})
        assert len(flags["governance_flags"]) <= 5

    def test_empty_sentiment_dict(self) -> None:
        flags = _extract_sentinel_flags("clean text", {})
        assert isinstance(flags["fraud_indicators"], list)
        assert isinstance(flags["regulatory_risks"], list)
        assert isinstance(flags["governance_flags"], list)


# ---------------------------------------------------------------------------
# Tests: _score_risk
# ---------------------------------------------------------------------------


class TestScoreRisk:
    def _make_sentinel(
        self,
        gov: int = 0,
        reg: int = 0,
        fraud: int = 0,
    ) -> dict[str, list[str]]:
        return {
            "governance_flags": [f"flag_{i}" for i in range(gov)],
            "regulatory_risks": [f"reg_{i}" for i in range(reg)],
            "fraud_indicators": [f"fraud_{i}" for i in range(fraud)],
        }

    def test_clean_company_low_risk_score(self) -> None:
        scores = _score_risk(
            _FUNDAMENTAL_GOOD,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["risk_score"] <= 4
        assert scores["governance_risk"] <= 4
        assert scores["financial_risk"] <= 4

    def test_risky_company_high_risk_score(self) -> None:
        scores = _score_risk(
            _FUNDAMENTAL_RISKY,
            _TECHNICAL_BEARISH,
            _SENTIMENT_RISKY,
            _MACRO_ADVERSE,
            self._make_sentinel(gov=3, reg=2, fraud=2),
        )
        assert scores["risk_score"] >= 6
        assert scores["financial_risk"] >= 6

    def test_high_de_raises_financial_risk(self) -> None:
        fundamental_high_de: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_high_de["debt_to_equity"] = 1.8
        scores = _score_risk(
            fundamental_high_de,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["financial_risk"] >= 5

    def test_moderate_de_moderate_financial_risk(self) -> None:
        fundamental_mod_de: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_mod_de["debt_to_equity"] = 0.7
        scores = _score_risk(
            fundamental_mod_de,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        # Moderate D/E should add 2 pts to financial_risk (base 3)
        assert scores["financial_risk"] >= 4

    def test_negative_de_net_cash_lowers_financial_risk(self) -> None:
        fundamental_cash: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_cash["debt_to_equity"] = -0.5
        scores_cash = _score_risk(
            fundamental_cash,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        scores_zero = _score_risk(
            _FUNDAMENTAL_GOOD,  # D/E 0.02
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        # Net cash should produce <= base financial risk
        assert scores_cash["financial_risk"] <= scores_zero["financial_risk"] + 1

    def test_many_red_flags_raises_governance_risk(self) -> None:
        sentiment_many_flags: dict[str, Any] = dict(_SENTIMENT_CLEAN)
        sentiment_many_flags["red_flag_count"] = 4
        scores = _score_risk(
            _FUNDAMENTAL_GOOD,
            _TECHNICAL_BULLISH,
            sentiment_many_flags,
            _MACRO_NEUTRAL,
            self._make_sentinel(gov=2),
        )
        assert scores["governance_risk"] >= 6

    def test_many_headwinds_raises_concentration_risk(self) -> None:
        scores = _score_risk(
            _FUNDAMENTAL_GOOD,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_ADVERSE,  # 3 headwinds
            self._make_sentinel(),
        )
        assert scores["concentration_risk"] >= 4

    def test_sell_signal_high_strength_raises_concentration_risk(self) -> None:
        scores = _score_risk(
            _FUNDAMENTAL_GOOD,
            _TECHNICAL_BEARISH,  # SELL, strength 8
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["concentration_risk"] >= 4

    def test_all_scores_within_bounds(self) -> None:
        scores = _score_risk(
            _FUNDAMENTAL_RISKY,
            _TECHNICAL_BEARISH,
            _SENTIMENT_RISKY,
            _MACRO_ADVERSE,
            self._make_sentinel(gov=5, reg=5, fraud=5),
        )
        for key in (
            "governance_risk",
            "regulatory_risk",
            "financial_risk",
            "concentration_risk",
            "risk_score",
        ):
            val = scores[key]
            assert 1 <= val <= 10, f"{key}={val} out of [1,10]"

    def test_none_de_handled_gracefully(self) -> None:
        fundamental_no_de: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_no_de["debt_to_equity"] = None
        scores = _score_risk(
            fundamental_no_de,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert 1 <= scores["risk_score"] <= 10

    def test_insufficient_data_quality_holds_financial_risk_at_neutral_base(
        self,
    ) -> None:
        """
        T-082: when fundamental.data_quality == 'insufficient', financial_risk
        must stay at the neutral base of 3 -- fragments like a lone high D/E
        must NOT push it up, and a missing score must NOT push it up either.
        """
        fundamental_insufficient: dict[str, Any] = {
            "agent_name": "fundamental_analyst",
            "data_quality": "insufficient",
            "score": None,
            # Even though a D/E fragment happens to be present and looks
            # risky, it must be ignored entirely while data_quality is
            # insufficient.
            "debt_to_equity": 2.5,
            "weaknesses": ["fcf negative and weak"],
            "summary": "",
        }
        scores = _score_risk(
            fundamental_insufficient,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["financial_risk"] == 3

    def test_sufficient_data_quality_still_applies_de_adjustment(self) -> None:
        """Sanity check: explicit data_quality='sufficient' does not disable
        the existing D/E-driven adjustment (regression guard for T-082)."""
        fundamental_sufficient: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_sufficient["data_quality"] = "sufficient"
        fundamental_sufficient["debt_to_equity"] = 1.8
        scores = _score_risk(
            fundamental_sufficient,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["financial_risk"] >= 5

    def test_missing_data_quality_key_defaults_to_sufficient(self) -> None:
        """
        Backward compatibility: fundamental dicts produced before T-081/T-082
        (no data_quality key at all) must behave exactly as before -- D/E
        adjustments still apply.
        """
        fundamental_high_de: dict[str, Any] = dict(_FUNDAMENTAL_GOOD)
        fundamental_high_de["debt_to_equity"] = 1.8
        assert "data_quality" not in fundamental_high_de
        scores = _score_risk(
            fundamental_high_de,
            _TECHNICAL_BULLISH,
            _SENTIMENT_CLEAN,
            _MACRO_NEUTRAL,
            self._make_sentinel(),
        )
        assert scores["financial_risk"] >= 5


# ---------------------------------------------------------------------------
# Tests: _determine_concentration_flags
# ---------------------------------------------------------------------------


class TestDetermineConcentrationFlags:
    def test_macro_headwinds_become_flags(self) -> None:
        flags = _determine_concentration_flags(
            _FUNDAMENTAL_GOOD, _MACRO_ADVERSE, _TECHNICAL_BULLISH
        )
        headwind_count = len([f for f in flags if "Macro headwind" in f])
        assert headwind_count >= 1

    def test_sector_headwind_flagged(self) -> None:
        flags = _determine_concentration_flags(
            _FUNDAMENTAL_GOOD, _MACRO_ADVERSE, _TECHNICAL_BULLISH
        )
        assert any("headwind" in f.lower() for f in flags)

    def test_sell_signal_creates_momentum_flag(self) -> None:
        flags = _determine_concentration_flags(
            _FUNDAMENTAL_GOOD, _MACRO_NEUTRAL, _TECHNICAL_BEARISH
        )
        assert any("momentum" in f.lower() for f in flags)

    def test_high_de_creates_leverage_flag(self) -> None:
        fundamental_high_de: dict[str, Any] = dict(_FUNDAMENTAL_RISKY)
        fundamental_high_de["debt_to_equity"] = 2.0
        flags = _determine_concentration_flags(
            fundamental_high_de, _MACRO_NEUTRAL, _TECHNICAL_BULLISH
        )
        assert any("leverage" in f.lower() or "debt" in f.lower() for f in flags)

    def test_clean_data_returns_few_flags(self) -> None:
        flags = _determine_concentration_flags(
            _FUNDAMENTAL_GOOD, _MACRO_NEUTRAL, _TECHNICAL_BULLISH
        )
        assert len(flags) <= 3

    def test_flags_capped_at_five(self) -> None:
        flags = _determine_concentration_flags(
            _FUNDAMENTAL_RISKY, _MACRO_ADVERSE, _TECHNICAL_BEARISH
        )
        assert len(flags) <= 5


# ---------------------------------------------------------------------------
# Tests: _determine_risk_recommendation
# ---------------------------------------------------------------------------


class TestDetermineRiskRecommendation:
    def test_low_score_proceed(self) -> None:
        assert _determine_risk_recommendation(1) == "proceed_with_caution"
        assert _determine_risk_recommendation(2) == "proceed_with_caution"
        assert _determine_risk_recommendation(3) == "proceed_with_caution"

    def test_mid_score_monitor(self) -> None:
        assert _determine_risk_recommendation(4) == "monitor_closely"
        assert _determine_risk_recommendation(5) == "monitor_closely"
        assert _determine_risk_recommendation(6) == "monitor_closely"

    def test_high_score_avoid(self) -> None:
        assert _determine_risk_recommendation(7) == "avoid"
        assert _determine_risk_recommendation(8) == "avoid"
        assert _determine_risk_recommendation(9) == "avoid"
        assert _determine_risk_recommendation(10) == "avoid"


# ---------------------------------------------------------------------------
# Tests: _build_risk_prompt
# ---------------------------------------------------------------------------


class TestBuildRiskPrompt:
    def _call(
        self,
        fundamental: dict[str, Any] = _FUNDAMENTAL_GOOD,
        technical: dict[str, Any] = _TECHNICAL_BULLISH,
        sentiment: dict[str, Any] = _SENTIMENT_CLEAN,
        macro: dict[str, Any] = _MACRO_NEUTRAL,
    ) -> str:
        scores = {
            "risk_score": 3,
            "governance_risk": 2,
            "regulatory_risk": 2,
            "financial_risk": 3,
            "concentration_risk": 3,
        }
        sentinel_flags: dict[str, list[str]] = {
            "governance_flags": [],
            "regulatory_risks": [],
            "fraud_indicators": [],
        }
        return _build_risk_prompt(
            company_name="TCS",
            ticker="TCS.NS",
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            scores=scores,
            sentinel_flags=sentinel_flags,
        )

    def test_company_name_in_prompt(self) -> None:
        prompt = self._call()
        assert "TCS" in prompt

    def test_risk_scores_in_prompt(self) -> None:
        prompt = self._call()
        assert "3/10" in prompt or "3" in prompt

    def test_fundamental_summary_in_prompt(self) -> None:
        prompt = self._call()
        assert "strong fcf" in prompt.lower() or "excellent" in prompt.lower()

    def test_red_flags_section_present(self) -> None:
        prompt = self._call(sentiment=_SENTIMENT_RISKY)
        assert "red flag" in prompt.lower() or "sebi" in prompt.lower()

    def test_headwinds_section_present(self) -> None:
        prompt = self._call(macro=_MACRO_ADVERSE)
        assert "headwind" in prompt.lower()

    def test_technical_signal_in_prompt(self) -> None:
        prompt = self._call()
        assert "BUY" in prompt

    def test_prompt_is_ascii_only(self) -> None:
        prompt = self._call()
        prompt.encode("ascii")  # raises UnicodeEncodeError if non-ASCII

    def test_none_values_formatted_as_na(self) -> None:
        fundamental_sparse: dict[str, Any] = {
            "score": 5,
            "debt_to_equity": None,
            "roe_pct": None,
            "summary": "Sparse data",
        }
        prompt = self._call(fundamental=fundamental_sparse)
        assert "N/A" in prompt


# ---------------------------------------------------------------------------
# Tests: _run_risk_analysis_core
# ---------------------------------------------------------------------------


class TestRunRiskAnalysisCore:
    @patch("backend.agents.risk_officer.get_llm")
    def test_clean_company_low_risk(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        assert isinstance(result, RiskAnalysis)
        assert result.risk_score <= 4
        assert result.error is None
        assert result.risk_recommendation == "proceed_with_caution"

    @patch("backend.agents.risk_officer.get_llm")
    def test_risky_company_high_risk(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_RISKY)
        result = _run_risk_analysis_core(
            analysis_id="t037-risky",
            company_name="Risky Corp",
            ticker="RISKY.NS",
            fundamental=_FUNDAMENTAL_RISKY,
            technical=_TECHNICAL_BEARISH,
            sentiment=_SENTIMENT_RISKY,
            macro=_MACRO_ADVERSE,
        )
        assert isinstance(result, RiskAnalysis)
        assert result.risk_score >= 6
        assert result.risk_recommendation in ("monitor_closely", "avoid")

    @patch("backend.agents.risk_officer.get_llm")
    def test_sebi_flag_appears_in_regulatory_risks(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_RISKY)
        result = _run_risk_analysis_core(
            analysis_id="t037-sebi",
            company_name="Risky Corp",
            ticker="RISKY.NS",
            fundamental=_FUNDAMENTAL_RISKY,
            technical=_TECHNICAL_BEARISH,
            sentiment=_SENTIMENT_RISKY,
            macro=_MACRO_NEUTRAL,
        )
        # SEBI keyword in sentiment red_flags should create regulatory risk flag
        all_flags = result.risk_flags
        has_sebi_flag = any("sebi" in f.lower() for f in all_flags)
        assert has_sebi_flag, f"No SEBI flag in risk_flags: {all_flags}"

    @patch("backend.agents.risk_officer.get_llm")
    def test_fraud_flag_appears_in_critical_flags(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_RISKY)
        result = _run_risk_analysis_core(
            analysis_id="t037-fraud",
            company_name="Risky Corp",
            ticker="RISKY.NS",
            fundamental=_FUNDAMENTAL_RISKY,
            technical=_TECHNICAL_BEARISH,
            sentiment=_SENTIMENT_RISKY,
            macro=_MACRO_NEUTRAL,
        )
        # Fraud probe keyword in sentiment should surface as critical flag
        has_critical = len(result.critical_flags) >= 1
        assert has_critical, f"Expected critical_flags but got: {result.critical_flags}"

    @patch("backend.agents.risk_officer.get_llm")
    def test_output_is_frozen_pydantic_model(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            result.risk_score = 99  # type: ignore[misc]

    @patch("backend.agents.risk_officer.get_llm")
    def test_model_dump_is_json_serialisable(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        dumped = result.model_dump()
        # Should not raise
        json.dumps(dumped, default=str)

    @patch("backend.agents.risk_officer.get_llm")
    def test_empty_research_dicts_do_not_raise(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental={},
            technical={},
            sentiment={},
            macro={},
        )
        assert isinstance(result, RiskAnalysis)
        assert 1 <= result.risk_score <= 10

    @patch("backend.agents.risk_officer.get_llm")
    def test_llm_failure_returns_error_free_model(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM quota exceeded")
        mock_get_llm.return_value = mock_llm

        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        assert isinstance(result, RiskAnalysis)
        # No error on the model itself (LLM failure is non-fatal)
        assert result.error is None
        # Summary should contain fallback text
        assert result.risk_score >= 1
        assert len(result.summary) > 0

    @patch("backend.agents.risk_officer.get_llm")
    def test_llm_returns_invalid_json_gracefully(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm("NOT VALID JSON AT ALL {{{")
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        assert isinstance(result, RiskAnalysis)
        assert 1 <= result.risk_score <= 10

    @patch("backend.agents.risk_officer.get_llm")
    def test_llm_invalid_recommendation_ignored(self, mock_get_llm: MagicMock) -> None:
        # LLM returns unrecognised recommendation -- should fall back to score-based
        bad_json = json.dumps(
            {
                "governance_flags": [],
                "regulatory_risks": [],
                "fraud_indicators": [],
                "concentration_risks": [],
                "risk_recommendation": "BUY_IT_ALL",  # invalid
                "summary": "Test summary",
            }
        )
        mock_get_llm.return_value = _make_llm(bad_json)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        assert result.risk_recommendation in (
            "proceed_with_caution",
            "monitor_closely",
            "avoid",
        )

    @patch("backend.agents.risk_officer.get_llm")
    def test_all_required_fields_populated(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        result = _run_risk_analysis_core(
            **_BASE_KWARGS,
            fundamental=_FUNDAMENTAL_GOOD,
            technical=_TECHNICAL_BULLISH,
            sentiment=_SENTIMENT_CLEAN,
            macro=_MACRO_NEUTRAL,
        )
        assert result.agent_name == "risk_officer"
        assert result.analysis_id == "t037-test-uuid"
        assert result.company_name == "Tata Consultancy Services"
        assert result.ticker == "TCS.NS"
        assert 1 <= result.governance_risk <= 10
        assert 1 <= result.regulatory_risk <= 10
        assert 1 <= result.financial_risk <= 10
        assert 1 <= result.concentration_risk <= 10
        assert isinstance(result.risk_flags, list)
        assert isinstance(result.critical_flags, list)
        assert len(result.summary) > 0


# ---------------------------------------------------------------------------
# Tests: run_risk_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunRiskAnalysisNode:
    def _make_state(
        self,
        ticker: str = "TCS.NS",
        company_name: str = "Tata Consultancy Services",
        job_id: str = "test-job-001",
        fundamental: dict[str, Any] | None = None,
        technical: dict[str, Any] | None = None,
        sentiment: dict[str, Any] | None = None,
        macro: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "company_name": company_name,
            "ticker": ticker,
            "fundamental": fundamental or _FUNDAMENTAL_GOOD,
            "technical": technical or _TECHNICAL_BULLISH,
            "sentiment": sentiment or _SENTIMENT_CLEAN,
            "macro": macro or _MACRO_NEUTRAL,
        }

    @patch("backend.agents.risk_officer.get_llm")
    def test_returns_dict_with_risk_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        assert "risk" in result
        assert isinstance(result["risk"], dict)

    @patch("backend.agents.risk_officer.get_llm")
    def test_returns_risk_flags_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        assert "risk_flags" in result
        assert isinstance(result["risk_flags"], list)

    @patch("backend.agents.risk_officer.get_llm")
    def test_returns_critical_flags_key(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        assert "critical_flags" in result
        assert isinstance(result["critical_flags"], list)

    @patch("backend.agents.risk_officer.get_llm")
    def test_risk_dict_has_required_fields(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        risk_dict = result["risk"]
        for field in (
            "agent_name",
            "risk_score",
            "governance_risk",
            "regulatory_risk",
            "financial_risk",
            "concentration_risk",
            "risk_flags",
            "critical_flags",
            "risk_recommendation",
            "summary",
        ):
            assert field in risk_dict, f"Missing field: {field}"

    def test_missing_ticker_returns_error_result(self) -> None:
        state: dict[str, Any] = {
            "job_id": "test-empty-ticker",
            "company_name": "Test Corp",
            "ticker": "",
            "fundamental": {},
        }
        result = run_risk_analysis(state)
        assert "risk" in result
        risk_dict = result["risk"]
        assert risk_dict.get("error") is not None
        assert risk_dict["risk_score"] == 5

    @patch("backend.agents.risk_officer.get_llm")
    def test_none_research_dicts_handled(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state: dict[str, Any] = {
            "job_id": "test-none-research",
            "company_name": "Test Corp",
            "ticker": "TEST.NS",
            "fundamental": None,
            "technical": None,
            "sentiment": None,
            "macro": None,
        }
        result = run_risk_analysis(state)
        assert "risk" in result
        assert 1 <= result["risk"]["risk_score"] <= 10

    @patch("backend.agents.risk_officer.get_llm")
    def test_result_is_json_serialisable(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        # Should not raise
        json.dumps(result, default=str)

    @patch("backend.agents.risk_officer.get_llm")
    def test_risk_score_within_bounds(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        state = self._make_state()
        result = run_risk_analysis(state)
        risk_score = result["risk"]["risk_score"]
        assert 1 <= risk_score <= 10

    @patch("backend.agents.risk_officer.get_llm")
    def test_risky_state_elevates_score(self, mock_get_llm: MagicMock) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_RISKY)
        state = self._make_state(
            ticker="RISKY.NS",
            company_name="Risky Corp",
            fundamental=_FUNDAMENTAL_RISKY,
            technical=_TECHNICAL_BEARISH,
            sentiment=_SENTIMENT_RISKY,
            macro=_MACRO_ADVERSE,
        )
        result = run_risk_analysis(state)
        assert result["risk"]["risk_score"] >= 5

    @patch("backend.agents.risk_officer.get_llm")
    def test_risk_flags_populated_for_risky_company(
        self, mock_get_llm: MagicMock
    ) -> None:
        mock_get_llm.return_value = _make_llm(_LLM_JSON_RISKY)
        state = self._make_state(
            ticker="RISKY.NS",
            company_name="Risky Corp",
            fundamental=_FUNDAMENTAL_RISKY,
            technical=_TECHNICAL_BEARISH,
            sentiment=_SENTIMENT_RISKY,
            macro=_MACRO_ADVERSE,
        )
        result = run_risk_analysis(state)
        assert len(result["risk_flags"]) >= 1

    @patch("backend.agents.risk_officer.get_llm")
    def test_upstream_risk_flags_preserved(self, mock_get_llm: MagicMock) -> None:
        """Flags written by error_handler or sentiment_escalation must survive.

        Regression test for the bug where run_risk_analysis overwrote
        risk_flags/critical_flags set by upstream nodes (T-037 fix).
        """
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        upstream_flag = "FUNDAMENTAL_DATA_UNAVAILABLE"
        state: dict[str, Any] = {
            "job_id": "test-upstream",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "fundamental": _FUNDAMENTAL_GOOD,
            "technical": _TECHNICAL_BULLISH,
            "sentiment": _SENTIMENT_CLEAN,
            "macro": _MACRO_NEUTRAL,
            # Simulate what error_handler_node wrote before risk_officer ran
            "risk_flags": [upstream_flag],
            "critical_flags": [upstream_flag],
        }
        result = run_risk_analysis(state)
        assert (
            upstream_flag in result["risk_flags"]
        ), f"{upstream_flag!r} was dropped from risk_flags by Risk Officer"
        assert (
            upstream_flag in result["critical_flags"]
        ), f"{upstream_flag!r} was dropped from critical_flags by Risk Officer"

    @patch("backend.agents.risk_officer.get_llm")
    def test_upstream_sentiment_escalation_flag_preserved(
        self, mock_get_llm: MagicMock
    ) -> None:
        """NEGATIVE_SENTIMENT flag from sentiment_escalation_node must survive."""
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        escalation_flag = "NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH"
        state: dict[str, Any] = {
            "job_id": "test-escalation",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "fundamental": _FUNDAMENTAL_GOOD,
            "technical": _TECHNICAL_BULLISH,
            "sentiment": _SENTIMENT_CLEAN,
            "macro": _MACRO_NEUTRAL,
            "risk_flags": [escalation_flag],
            "critical_flags": [],
        }
        result = run_risk_analysis(state)
        assert (
            escalation_flag in result["risk_flags"]
        ), f"{escalation_flag!r} was dropped from risk_flags by Risk Officer"

    @patch("backend.agents.risk_officer.get_llm")
    def test_upstream_flags_not_duplicated(self, mock_get_llm: MagicMock) -> None:
        """If an upstream flag also appears in Risk Officer output, no duplicates."""
        mock_get_llm.return_value = _make_llm(_LLM_JSON_CLEAN)
        existing_flag = "SOME_EXISTING_FLAG"
        state: dict[str, Any] = {
            "job_id": "test-dedup",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "fundamental": _FUNDAMENTAL_GOOD,
            "technical": _TECHNICAL_BULLISH,
            "sentiment": _SENTIMENT_CLEAN,
            "macro": _MACRO_NEUTRAL,
            "risk_flags": [existing_flag],
            "critical_flags": [],
        }
        result = run_risk_analysis(state)
        count = result["risk_flags"].count(existing_flag)
        assert count == 1, f"Flag duplicated: {existing_flag!r} appears {count} times"


# ---------------------------------------------------------------------------
# Tests: Schema validation (Pydantic constraints)
# ---------------------------------------------------------------------------


class TestRiskAnalysisSchemaValidation:
    _BASE: dict[str, Any] = {
        "agent_name": "risk_officer",
        "analysis_id": "schema-test",
        "company_name": "Test Corp",
        "ticker": "TEST.NS",
        "risk_score": 5,
        "governance_risk": 5,
        "regulatory_risk": 5,
        "financial_risk": 5,
        "concentration_risk": 5,
    }

    def test_valid_model_constructs_successfully(self) -> None:
        result = RiskAnalysis(**self._BASE)
        assert result.risk_score == 5

    def test_risk_score_below_1_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RiskAnalysis(**{**self._BASE, "risk_score": 0})

    def test_risk_score_above_10_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RiskAnalysis(**{**self._BASE, "risk_score": 11})

    def test_governance_risk_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RiskAnalysis(**{**self._BASE, "governance_risk": 0})

    def test_default_risk_flags_empty_list(self) -> None:
        result = RiskAnalysis(**self._BASE)
        assert result.risk_flags == []

    def test_default_critical_flags_empty_list(self) -> None:
        result = RiskAnalysis(**self._BASE)
        assert result.critical_flags == []

    def test_model_is_frozen(self) -> None:
        from pydantic import ValidationError

        result = RiskAnalysis(**self._BASE)
        with pytest.raises(ValidationError):
            result.risk_score = 99  # type: ignore[misc]

    def test_model_dump_round_trip(self) -> None:
        result = RiskAnalysis(
            **self._BASE,
            risk_flags=["High D/E ratio of 2.5x"],
            critical_flags=["SEBI notice pending"],
            risk_recommendation="avoid",
            summary="High risk.",
        )
        dumped = result.model_dump()
        assert dumped["risk_flags"] == ["High D/E ratio of 2.5x"]
        assert dumped["critical_flags"] == ["SEBI notice pending"]
        assert dumped["risk_recommendation"] == "avoid"


# ---------------------------------------------------------------------------
# Tests: SYSTEM_PROMPT content
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_contains_rules(self) -> None:
        assert "RULES:" in SYSTEM_PROMPT

    def test_system_prompt_contains_output_schema(self) -> None:
        assert "OUTPUT SCHEMA" in SYSTEM_PROMPT

    def test_system_prompt_mentions_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_is_ascii_only(self) -> None:
        SYSTEM_PROMPT.encode("ascii")

    def test_system_prompt_mentions_key_risk_dimensions(self) -> None:
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "governance" in prompt_lower
        assert "regulatory" in prompt_lower
        assert "fraud" in prompt_lower


# ---------------------------------------------------------------------------
# Tests: LangSmith tracing integration
# ---------------------------------------------------------------------------


class TestTracingIntegration:
    def test_run_risk_analysis_is_traced(self) -> None:
        """@traced_agent wraps the function; __wrapped__ exposes the original."""
        assert hasattr(
            run_risk_analysis, "__wrapped__"
        ), "run_risk_analysis is missing __wrapped__; @traced_agent was not applied"

    def test_wrapped_function_is_callable(self) -> None:
        # __wrapped__ is set by functools.wraps inside traced_agent decorator.
        # Use hasattr only -- direct attribute access causes mypy[misc] when
        # langsmith is installed in CI (warn_unused_ignores fires on strict mode).
        assert hasattr(run_risk_analysis, "__wrapped__")
        wrapped = getattr(run_risk_analysis, "__wrapped__", None)
        assert wrapped is not None
        assert callable(wrapped)
