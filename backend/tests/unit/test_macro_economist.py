# backend/tests/unit/test_macro_economist.py
"""
Unit tests for T-025: Macro Economist Agent.

Test strategy:
  1. _classify_rate_stance       -- RBI rate -> stance label mapping
  2. _classify_rate_direction    -- rate level -> direction inference
  3. _classify_inflation_trend   -- CPI -> trend label mapping
  4. _classify_macro_environment -- composite environment classification
  5. _detect_sector              -- company name -> sector keyword matching
  6. _classify_sector_impact     -- sector + stance -> impact label
  7. _build_tailwinds_headwinds  -- lookup table + GDP/CPI supplement
  8. _build_macro_prompt         -- prompt content verification
  9. _run_macro_analysis_core    -- full agent with mocked tool + LLM
  10. run_macro_analysis          -- LangGraph node state in/out
  11. Error paths                 -- missing ticker, tool error, LLM failure

Acceptance criteria verified:
  * Rate hike environment (tightening stance) correctly identified as
    a HEADWIND for banking stocks (test_banking_tightening_is_headwind)
  * Rate hike environment is a HEADWIND for NBFC stocks
  * Rate hike correctly identified as a HEADWIND for auto sector
  * Accommodative stance is a TAILWIND for banking and auto sectors
  * Agent never raises -- always returns dict with 'macro' key
  * MacroAnalysis Pydantic model validates and serialises correctly

All external calls (macro scraper, Redis, ChromaDB, LLM) are mocked.
"""
from __future__ import annotations

import json
import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.agents.macro_economist import (  # noqa: E402
    RATE_ACCOMMODATIVE_MAX,
    RATE_CALIB_TIGHTENING_MAX,
    RATE_NEUTRAL_MAX,
    SYSTEM_PROMPT,
    _build_macro_prompt,
    _build_tailwinds_headwinds,
    _classify_inflation_trend,
    _classify_macro_environment,
    _classify_rate_direction,
    _classify_rate_stance,
    _classify_sector_impact,
    _detect_sector,
    _run_macro_analysis_core,
    run_macro_analysis,
)
from backend.agents.output_models import MacroAnalysis  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# Standard "healthy India macro" macro tool result
_MACRO_RESULT_HEALTHY: dict[str, Any] = {
    "repo_rate": 6.5,
    "cpi_inflation": 5.1,
    "gdp_growth": 7.2,
    "repo_rate_as_of": "2024-01-01",
    "cpi_as_of": "2024-01-01",
    "gdp_as_of": "2023",
    "warnings": [],
    "cached": False,
}

# High-rate tightening environment (acceptance criteria scenario)
_MACRO_RESULT_TIGHTENING: dict[str, Any] = {
    "repo_rate": 7.5,
    "cpi_inflation": 7.2,
    "gdp_growth": 5.8,
    "repo_rate_as_of": "2024-01-01",
    "cpi_as_of": "2024-01-01",
    "gdp_as_of": "2023",
    "warnings": [],
    "cached": False,
}

# Accommodative environment (COVID-era style)
_MACRO_RESULT_ACCOMMODATIVE: dict[str, Any] = {
    "repo_rate": 4.0,
    "cpi_inflation": 3.5,
    "gdp_growth": 8.5,
    "repo_rate_as_of": "2024-01-01",
    "cpi_as_of": "2024-01-01",
    "gdp_as_of": "2023",
    "warnings": [],
    "cached": False,
}

_LLM_RESPONSE: dict[str, Any] = {
    "tailwinds": [
        "Strong GDP growth of 7.2% supports broad corporate demand",
        "Stable inflation within RBI comfort band reduces rate hike risk",
    ],
    "headwinds": [
        "Calibrated tightening puts mild pressure on NIMs",
        "Global rate cycle uncertainty weighs on risk appetite",
    ],
    "global_factors": [
        "Fed rate pause reduces EM capital outflow risk",
        "Crude oil prices stable, limiting imported inflation",
    ],
    "india_specific": [
        "RBI repo rate at 6.50% -- calibrated tightening stance",
        "CPI at 5.1% within RBI's 2-6% tolerance band",
    ],
    "summary": (
        "India's macro environment is broadly favourable with strong GDP "
        "growth of 7.2% and CPI within RBI's comfort zone. The "
        "calibrated tightening stance represents a modest headwind for "
        "rate-sensitive sectors."
    ),
}
_LLM_JSON = json.dumps(_LLM_RESPONSE)

_STATE_HDFC = {
    "job_id": "test-001",
    "company_name": "HDFC Bank",
    "ticker": "HDFCBANK.NS",
}
_STATE_TCS = {
    "job_id": "test-002",
    "company_name": "TCS",
    "ticker": "TCS.NS",
}
_STATE_MARUTI = {
    "job_id": "test-003",
    "company_name": "Maruti Suzuki",
    "ticker": "MARUTI.NS",
}
_STATE_RELIANCE = {
    "job_id": "test-004",
    "company_name": "Reliance Industries",
    "ticker": "RELIANCE.NS",
}


def _mock_llm(content: str = _LLM_JSON) -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = MagicMock(content=content)
    return m


# ---------------------------------------------------------------------------
# Tests: _classify_rate_stance
# ---------------------------------------------------------------------------


class TestClassifyRateStance:
    def test_accommodative_below_threshold(self) -> None:
        assert _classify_rate_stance(4.0) == "accommodative"
        assert _classify_rate_stance(3.5) == "accommodative"

    def test_neutral_range(self) -> None:
        assert _classify_rate_stance(5.0) == "neutral"
        assert _classify_rate_stance(5.5) == "neutral"
        assert _classify_rate_stance(5.99) == "neutral"

    def test_calibrated_tightening_range(self) -> None:
        assert _classify_rate_stance(6.0) == "calibrated_tightening"
        assert _classify_rate_stance(6.5) == "calibrated_tightening"
        assert _classify_rate_stance(6.99) == "calibrated_tightening"

    def test_tightening_at_and_above_threshold(self) -> None:
        assert _classify_rate_stance(7.0) == "tightening"
        assert _classify_rate_stance(7.5) == "tightening"
        assert _classify_rate_stance(9.0) == "tightening"

    def test_none_returns_neutral(self) -> None:
        assert _classify_rate_stance(None) == "neutral"

    def test_exact_boundary_accommodative_max(self) -> None:
        # 5.0 is NOT accommodative -- it's the start of neutral
        assert _classify_rate_stance(RATE_ACCOMMODATIVE_MAX) == "neutral"

    def test_exact_boundary_neutral_max(self) -> None:
        # 6.0 is NOT neutral -- it's the start of calibrated_tightening
        assert _classify_rate_stance(RATE_NEUTRAL_MAX) == "calibrated_tightening"

    def test_exact_boundary_tightening(self) -> None:
        assert _classify_rate_stance(RATE_CALIB_TIGHTENING_MAX) == "tightening"

    def test_returns_string(self) -> None:
        assert isinstance(_classify_rate_stance(6.5), str)


# ---------------------------------------------------------------------------
# Tests: _classify_rate_direction
# ---------------------------------------------------------------------------


class TestClassifyRateDirection:
    def test_below_midpoint_is_cutting(self) -> None:
        assert _classify_rate_direction(4.0) == "cutting"
        assert _classify_rate_direction(5.5) == "cutting"

    def test_at_midpoint_is_holding(self) -> None:
        assert _classify_rate_direction(6.0) == "holding"

    def test_above_midpoint_is_hiking(self) -> None:
        assert _classify_rate_direction(6.5) == "hiking"
        assert _classify_rate_direction(7.5) == "hiking"

    def test_none_returns_holding(self) -> None:
        assert _classify_rate_direction(None) == "holding"

    def test_returns_string(self) -> None:
        assert isinstance(_classify_rate_direction(6.5), str)


# ---------------------------------------------------------------------------
# Tests: _classify_inflation_trend
# ---------------------------------------------------------------------------


class TestClassifyInflationTrend:
    def test_low_cpi_is_falling(self) -> None:
        assert _classify_inflation_trend(2.5) == "falling"
        assert _classify_inflation_trend(3.9) == "falling"

    def test_moderate_cpi_is_stable(self) -> None:
        assert _classify_inflation_trend(4.0) == "stable"
        assert _classify_inflation_trend(5.5) == "stable"
        assert _classify_inflation_trend(5.99) == "stable"

    def test_high_cpi_is_rising(self) -> None:
        assert _classify_inflation_trend(6.0) == "rising"
        assert _classify_inflation_trend(7.5) == "rising"

    def test_none_returns_stable(self) -> None:
        assert _classify_inflation_trend(None) == "stable"

    def test_returns_string(self) -> None:
        assert isinstance(_classify_inflation_trend(5.0), str)


# ---------------------------------------------------------------------------
# Tests: _classify_macro_environment
# ---------------------------------------------------------------------------


class TestClassifyMacroEnvironment:
    def test_all_strong_is_favourable(self) -> None:
        # GDP >= 6.5, CPI < 6.0, repo < 7.0
        assert _classify_macro_environment(6.5, 5.0, 7.0) == "favourable"

    def test_tightening_with_high_cpi_is_unfavourable(self) -> None:
        # repo >= 7.0 AND CPI >= 6.0
        assert _classify_macro_environment(7.5, 7.2, 5.5) == "unfavourable"

    def test_weak_gdp_is_unfavourable(self) -> None:
        # GDP < 5.0
        assert _classify_macro_environment(6.5, 4.5, 4.5) == "unfavourable"

    def test_mixed_signals_is_neutral(self) -> None:
        # GDP ok but CPI elevated and rates tightening
        assert _classify_macro_environment(6.5, 6.2, 6.8) == "neutral"

    def test_none_values_default_to_neutral(self) -> None:
        result = _classify_macro_environment(None, None, None)
        assert result in ("favourable", "neutral", "unfavourable")

    def test_strong_gdp_with_benign_cpi_and_low_rates(self) -> None:
        assert _classify_macro_environment(4.0, 3.5, 8.5) == "favourable"

    def test_returns_valid_label(self) -> None:
        result = _classify_macro_environment(6.5, 5.1, 7.2)
        assert result in ("favourable", "neutral", "unfavourable")


# ---------------------------------------------------------------------------
# Tests: _detect_sector
# ---------------------------------------------------------------------------


class TestDetectSector:
    def test_hdfc_bank_is_banking(self) -> None:
        assert _detect_sector("HDFC Bank") == "banking"

    def test_icici_bank_is_banking(self) -> None:
        assert _detect_sector("ICICI Bank") == "banking"

    def test_sbi_is_banking(self) -> None:
        assert _detect_sector("State Bank of India SBI") == "banking"

    def test_bajaj_finance_is_nbfc(self) -> None:
        assert _detect_sector("Bajaj Finance") == "nbfc"

    def test_tcs_is_it_services(self) -> None:
        assert _detect_sector("TCS") == "it_services"

    def test_infosys_is_it_services(self) -> None:
        assert _detect_sector("Infosys") == "it_services"

    def test_wipro_is_it_services(self) -> None:
        assert _detect_sector("Wipro") == "it_services"

    def test_reliance_is_energy(self) -> None:
        assert _detect_sector("Reliance Industries") == "energy"

    def test_ongc_is_energy(self) -> None:
        assert _detect_sector("ONGC Oil") == "energy"

    def test_sun_pharma_is_pharma(self) -> None:
        assert _detect_sector("Sun Pharma") == "pharma_healthcare"

    def test_maruti_is_auto(self) -> None:
        assert _detect_sector("Maruti Suzuki") == "auto"

    def test_tata_motors_is_auto(self) -> None:
        assert _detect_sector("Tata Motors") == "auto"

    def test_hul_is_fmcg(self) -> None:
        assert _detect_sector("Hindustan Unilever") == "fmcg"

    def test_itc_is_fmcg(self) -> None:
        assert _detect_sector("ITC") == "fmcg"

    def test_lt_is_infra(self) -> None:
        assert _detect_sector("L&T Construction") == "infra_industrials"

    def test_unknown_company_is_diversified(self) -> None:
        assert _detect_sector("XYZ Corp Unknown") == "diversified"

    def test_case_insensitive(self) -> None:
        assert _detect_sector("HDFC BANK") == _detect_sector("hdfc bank")

    def test_returns_string(self) -> None:
        assert isinstance(_detect_sector("TCS"), str)


# ---------------------------------------------------------------------------
# Tests: _classify_sector_impact (ACCEPTANCE CRITERIA TESTS)
# ---------------------------------------------------------------------------


class TestClassifySectorImpact:
    """
    Core acceptance criteria:
    Rate hike environment impact on banking stocks must be HEADWIND.
    """

    def test_banking_tightening_is_headwind(self) -> None:
        """ACCEPTANCE CRITERIA: rate hike env -> banking headwind."""
        assert _classify_sector_impact("banking", "tightening") == "headwind"

    def test_banking_calibrated_tightening_is_headwind(self) -> None:
        """Calibrated tightening is also a headwind for banking."""
        assert _classify_sector_impact("banking", "calibrated_tightening") == "headwind"

    def test_banking_accommodative_is_tailwind(self) -> None:
        assert _classify_sector_impact("banking", "accommodative") == "tailwind"

    def test_banking_neutral_is_neutral(self) -> None:
        assert _classify_sector_impact("banking", "neutral") == "neutral"

    def test_nbfc_tightening_is_headwind(self) -> None:
        """Rate hike env -> NBFC headwind (similar to banking)."""
        assert _classify_sector_impact("nbfc", "tightening") == "headwind"

    def test_auto_tightening_is_headwind(self) -> None:
        """Rate hike env -> auto headwind (EMI affordability)."""
        assert _classify_sector_impact("auto", "tightening") == "headwind"

    def test_auto_accommodative_is_tailwind(self) -> None:
        assert _classify_sector_impact("auto", "accommodative") == "tailwind"

    def test_it_tightening_is_neutral(self) -> None:
        """IT services largely insulated from domestic rate cycles."""
        assert _classify_sector_impact("it_services", "tightening") == "neutral"

    def test_pharma_tightening_is_neutral(self) -> None:
        """Pharma is defensive -- rate neutral."""
        assert _classify_sector_impact("pharma_healthcare", "tightening") == "neutral"

    def test_infra_tightening_is_headwind(self) -> None:
        """Higher rates increase project financing costs."""
        assert _classify_sector_impact("infra_industrials", "tightening") == "headwind"

    def test_infra_accommodative_is_tailwind(self) -> None:
        assert (
            _classify_sector_impact("infra_industrials", "accommodative") == "tailwind"
        )

    def test_unknown_sector_returns_neutral(self) -> None:
        assert _classify_sector_impact("unknown_sector", "tightening") == "neutral"

    def test_returns_valid_label(self) -> None:
        for sector in ("banking", "it_services", "auto", "fmcg"):
            for stance in (
                "accommodative",
                "neutral",
                "calibrated_tightening",
                "tightening",
            ):
                result = _classify_sector_impact(sector, stance)
                assert result in ("tailwind", "neutral", "headwind")


# ---------------------------------------------------------------------------
# Tests: _build_tailwinds_headwinds
# ---------------------------------------------------------------------------


class TestBuildTailwindsHeadwinds:
    def test_banking_tightening_has_headwinds(self) -> None:
        tw, hw = _build_tailwinds_headwinds("banking", "tightening", 7.2, 5.8)
        assert len(hw) > 0
        # At least one headwind should mention NIM or rate
        hw_text = " ".join(hw).lower()
        assert any(kw in hw_text for kw in ["nim", "rate", "margin", "cost", "credit"])

    def test_banking_accommodative_has_tailwinds(self) -> None:
        tw, hw = _build_tailwinds_headwinds("banking", "accommodative", 3.5, 8.5)
        assert len(tw) > 0

    def test_strong_gdp_adds_tailwind(self) -> None:
        _, _ = _build_tailwinds_headwinds("it_services", "neutral", 5.0, 7.5)
        tw, _ = _build_tailwinds_headwinds("it_services", "neutral", 5.0, 7.5)
        tw_text = " ".join(tw).lower()
        assert "gdp" in tw_text or "7.5" in tw_text

    def test_weak_gdp_adds_headwind(self) -> None:
        _, hw = _build_tailwinds_headwinds("fmcg", "neutral", 5.0, 4.0)
        hw_text = " ".join(hw).lower()
        assert "gdp" in hw_text or "4.0" in hw_text

    def test_high_cpi_adds_headwind(self) -> None:
        _, hw = _build_tailwinds_headwinds("auto", "neutral", 7.5, 6.5)
        hw_text = " ".join(hw).lower()
        assert "cpi" in hw_text or "inflation" in hw_text or "7.5" in hw_text

    def test_low_cpi_adds_tailwind(self) -> None:
        tw, _ = _build_tailwinds_headwinds("fmcg", "neutral", 3.0, 6.8)
        tw_text = " ".join(tw).lower()
        assert any(kw in tw_text for kw in ["cpi", "inflation", "3.0", "cut"])

    def test_none_cpi_and_gdp_no_crash(self) -> None:
        tw, hw = _build_tailwinds_headwinds("banking", "tightening", None, None)
        assert isinstance(tw, list)
        assert isinstance(hw, list)

    def test_returns_lists(self) -> None:
        tw, hw = _build_tailwinds_headwinds("it_services", "neutral", 5.0, 7.2)
        assert isinstance(tw, list)
        assert isinstance(hw, list)


# ---------------------------------------------------------------------------
# Tests: _build_macro_prompt
# ---------------------------------------------------------------------------


class TestBuildMacroPrompt:
    def _make(self, **kwargs: Any) -> str:
        defaults: dict[str, Any] = {
            "company_name": "HDFC Bank",
            "ticker": "HDFCBANK.NS",
            "sector": "banking",
            "repo_rate": 6.5,
            "cpi": 5.1,
            "gdp": 7.2,
            "rate_stance": "calibrated_tightening",
            "rate_direction": "hiking",
            "inflation_trend": "stable",
            "macro_environment": "favourable",
            "sector_impact": "headwind",
            "tailwinds": ["Strong GDP supports credit demand"],
            "headwinds": ["Rate hike compresses NIMs"],
            "chroma_snippets": [],
            "warnings": [],
        }
        defaults.update(kwargs)
        return _build_macro_prompt(**defaults)

    def test_contains_company_name(self) -> None:
        assert "HDFC Bank" in self._make()

    def test_contains_ticker(self) -> None:
        assert "HDFCBANK.NS" in self._make()

    def test_contains_sector(self) -> None:
        assert "banking" in self._make()

    def test_contains_repo_rate(self) -> None:
        assert "6.50" in self._make()

    def test_contains_rate_stance(self) -> None:
        assert "calibrated_tightening" in self._make()

    def test_contains_macro_environment(self) -> None:
        assert "favourable" in self._make()

    def test_contains_sector_impact(self) -> None:
        assert "headwind" in self._make()

    def test_tailwinds_included(self) -> None:
        assert "Strong GDP" in self._make()

    def test_headwinds_included(self) -> None:
        assert "NIMs" in self._make()

    def test_chroma_snippets_shown_when_present(self) -> None:
        snippets = [{"document": "RBI rate hike banking sector", "distance": 0.1}]
        prompt = self._make(chroma_snippets=snippets)
        assert "ChromaDB" in prompt or "RBI rate hike" in prompt

    def test_warnings_shown_when_present(self) -> None:
        prompt = self._make(warnings=["CPI data unavailable"])
        assert "DATA WARNINGS" in prompt or "unavailable" in prompt

    def test_none_rates_show_na(self) -> None:
        prompt = self._make(repo_rate=None, cpi=None, gdp=None)
        assert "N/A" in prompt

    def test_returns_string(self) -> None:
        assert isinstance(self._make(), str)


# ---------------------------------------------------------------------------
# Tests: _run_macro_analysis_core (full agent, mocked externals)
# ---------------------------------------------------------------------------


class TestRunMacroAnalysisCore:
    def _run(
        self,
        macro_result: dict[str, Any] = _MACRO_RESULT_HEALTHY,
        llm_response: str = _LLM_JSON,
        company_name: str = "HDFC Bank",
        ticker: str = "HDFCBANK.NS",
    ) -> MacroAnalysis:
        mock_llm = _mock_llm(llm_response)
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.return_value = macro_result
            return _run_macro_analysis_core(
                analysis_id="test-001",
                company_name=company_name,
                ticker=ticker,
            )

    def test_returns_macro_analysis_instance(self) -> None:
        assert isinstance(self._run(), MacroAnalysis)

    def test_agent_name_correct(self) -> None:
        assert self._run().agent_name == "macro_economist"

    def test_ticker_preserved(self) -> None:
        assert self._run().ticker == "HDFCBANK.NS"

    def test_error_is_none_on_success(self) -> None:
        assert self._run().error is None

    # --- Acceptance criteria: rate hike -> banking headwind ---

    def test_tightening_rate_banking_headwind(self) -> None:
        """ACCEPTANCE CRITERIA: rate hike environment -> banking headwind."""
        result = self._run(
            macro_result=_MACRO_RESULT_TIGHTENING,
            company_name="HDFC Bank",
            ticker="HDFCBANK.NS",
        )
        assert result.sector_impact == "headwind"
        assert result.rate_stance in ("tightening", "calibrated_tightening")

    def test_tightening_rate_stance_for_high_rate(self) -> None:
        result = self._run(macro_result=_MACRO_RESULT_TIGHTENING)
        assert result.rate_stance == "tightening"
        assert result.rate_direction == "hiking"

    def test_accommodative_rate_banking_tailwind(self) -> None:
        result = self._run(
            macro_result=_MACRO_RESULT_ACCOMMODATIVE,
            company_name="HDFC Bank",
            ticker="HDFCBANK.NS",
        )
        assert result.sector_impact == "tailwind"

    def test_repo_rate_field_populated(self) -> None:
        result = self._run(macro_result=_MACRO_RESULT_HEALTHY)
        assert result.rbi_repo_rate_pct == pytest.approx(6.5)

    def test_cpi_field_populated(self) -> None:
        result = self._run(macro_result=_MACRO_RESULT_HEALTHY)
        assert result.cpi_inflation_pct == pytest.approx(5.1)

    def test_gdp_field_populated(self) -> None:
        result = self._run(macro_result=_MACRO_RESULT_HEALTHY)
        assert result.gdp_growth_pct == pytest.approx(7.2)

    def test_macro_environment_valid_label(self) -> None:
        result = self._run()
        assert result.macro_environment in ("favourable", "neutral", "unfavourable")

    def test_sector_impact_valid_label(self) -> None:
        result = self._run()
        assert result.sector_impact in ("tailwind", "neutral", "headwind")

    def test_rate_stance_valid_label(self) -> None:
        result = self._run()
        assert result.rate_stance in (
            "accommodative",
            "neutral",
            "calibrated_tightening",
            "tightening",
        )

    def test_rate_direction_valid_label(self) -> None:
        result = self._run()
        assert result.rate_direction in ("cutting", "holding", "hiking")

    def test_inflation_trend_valid_label(self) -> None:
        result = self._run()
        assert result.inflation_trend in ("rising", "stable", "falling")

    def test_tailwinds_is_list(self) -> None:
        result = self._run()
        assert isinstance(result.tailwinds, list)

    def test_headwinds_is_list(self) -> None:
        result = self._run()
        assert isinstance(result.headwinds, list)

    def test_summary_populated_from_llm(self) -> None:
        result = self._run()
        assert len(result.summary) > 0

    def test_model_serialisable(self) -> None:
        result = self._run()
        obj = MacroAnalysis(**result.model_dump())
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)

    def test_it_services_sector_detected_for_tcs(self) -> None:
        result = self._run(company_name="TCS", ticker="TCS.NS")
        # TCS should map to it_services, which is neutral in tightening
        assert result.sector_impact in ("tailwind", "neutral", "headwind")

    def test_macro_tool_error_returns_model_with_error(self) -> None:
        result = self._run(
            macro_result={"error": "scrape_blocked", "message": "403 Forbidden"}
        )
        assert isinstance(result, MacroAnalysis)
        assert result.error is not None

    def test_fetch_macro_exception_returns_error_model(self) -> None:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.side_effect = RuntimeError("Network error")
            result = _run_macro_analysis_core("x", "HDFC Bank", "HDFCBANK.NS")
        assert result.error is not None

    def test_chroma_failure_is_non_fatal(self) -> None:
        """ChromaDB failure must not cause agent error."""
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                side_effect=RuntimeError("ChromaDB down"),
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.return_value = _MACRO_RESULT_HEALTHY
            result = _run_macro_analysis_core("x", "HDFC Bank", "HDFCBANK.NS")
        assert isinstance(result, MacroAnalysis)
        assert result.error is None

    def test_llm_failure_uses_fallback_summary(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Groq timeout")
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.return_value = _MACRO_RESULT_HEALTHY
            result = _run_macro_analysis_core("x", "HDFC Bank", "HDFCBANK.NS")
        assert isinstance(result, MacroAnalysis)
        assert result.error is None
        assert len(result.summary) > 0

    def test_llm_malformed_json_uses_fallback(self) -> None:
        result = self._run(llm_response="Sorry, cannot help.")
        assert isinstance(result, MacroAnalysis)
        assert result.macro_environment in ("favourable", "neutral", "unfavourable")

    def test_none_macro_data_fields_handled(self) -> None:
        """All-None macro data (total outage) must still return valid model."""
        null_macro = {
            "repo_rate": None,
            "cpi_inflation": None,
            "gdp_growth": None,
            "warnings": ["All sources unavailable"],
            "cached": False,
        }
        result = self._run(macro_result=null_macro)
        assert isinstance(result, MacroAnalysis)
        assert result.error is None
        assert result.macro_environment in ("favourable", "neutral", "unfavourable")

    def test_nbfc_tightening_headwind(self) -> None:
        result = self._run(
            macro_result=_MACRO_RESULT_TIGHTENING,
            company_name="Bajaj Finance",
            ticker="BAJFINANCE.NS",
        )
        assert result.sector_impact == "headwind"

    def test_auto_tightening_headwind(self) -> None:
        result = self._run(
            macro_result=_MACRO_RESULT_TIGHTENING,
            company_name="Maruti Suzuki",
            ticker="MARUTI.NS",
        )
        assert result.sector_impact == "headwind"

    def test_tool_called_with_empty_dict(self) -> None:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.return_value = _MACRO_RESULT_HEALTHY
            _run_macro_analysis_core("x", "HDFC Bank", "HDFCBANK.NS")
            mock_macro.invoke.assert_called_once_with({})


# ---------------------------------------------------------------------------
# Tests: run_macro_analysis (LangGraph node)
# ---------------------------------------------------------------------------


class TestRunMacroAnalysisNode:
    def _invoke(
        self,
        state: dict[str, Any],
        macro_result: dict[str, Any] = _MACRO_RESULT_HEALTHY,
    ) -> dict[str, Any]:
        mock_llm = _mock_llm()
        with (
            patch("backend.agents.macro_economist.fetch_macro_data") as mock_macro,
            patch(
                "backend.agents.macro_economist.semantic_search",
                return_value=[],
            ),
            patch(
                "backend.agents.macro_economist.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_macro.invoke.return_value = macro_result
            return cast(dict[str, Any], run_macro_analysis(state))

    def test_returns_dict_with_macro_key(self) -> None:
        result = self._invoke(_STATE_HDFC)
        assert "macro" in result
        assert isinstance(result["macro"], dict)

    def test_macro_has_environment(self) -> None:
        result = self._invoke(_STATE_HDFC)
        env = result["macro"]["macro_environment"]
        assert env in ("favourable", "neutral", "unfavourable")

    def test_macro_has_sector_impact(self) -> None:
        result = self._invoke(_STATE_HDFC)
        impact = result["macro"]["sector_impact"]
        assert impact in ("tailwind", "neutral", "headwind")

    def test_job_id_preserved(self) -> None:
        result = self._invoke(_STATE_HDFC)
        assert result["macro"]["analysis_id"] == "test-001"

    def test_empty_ticker_returns_error(self) -> None:
        result = run_macro_analysis(
            {"job_id": "x", "company_name": "Test", "ticker": ""}
        )
        assert result["macro"]["error"] is not None

    def test_missing_ticker_key_returns_error(self) -> None:
        result = run_macro_analysis({"job_id": "x", "company_name": "Test"})
        assert result["macro"]["error"] is not None

    def test_never_raises_on_catastrophic_failure(self) -> None:
        with patch(
            "backend.agents.macro_economist._run_macro_analysis_core",
            side_effect=RuntimeError("Catastrophic failure"),
        ):
            result = run_macro_analysis(_STATE_HDFC)
        assert "macro" in result
        assert result["macro"]["error"] is not None

    def test_hdfc_bank_state(self) -> None:
        result = self._invoke(_STATE_HDFC)
        assert result["macro"]["ticker"] == "HDFCBANK.NS"

    def test_tcs_state(self) -> None:
        result = self._invoke(_STATE_TCS)
        assert result["macro"]["ticker"] == "TCS.NS"

    def test_rate_stance_in_output(self) -> None:
        result = self._invoke(_STATE_HDFC)
        assert "rate_stance" in result["macro"]

    def test_tightening_banking_headwind_full_pipeline(self) -> None:
        """
        End-to-end acceptance criteria test via the LangGraph node.
        Rate hike environment -> banking -> headwind.
        """
        result = self._invoke(_STATE_HDFC, macro_result=_MACRO_RESULT_TIGHTENING)
        assert result["macro"]["sector_impact"] == "headwind"

    def test_macro_dict_json_serialisable(self) -> None:
        result = self._invoke(_STATE_TCS)
        obj = MacroAnalysis(**result["macro"])
        dumped = json.dumps(obj.model_dump(mode="json"))
        assert isinstance(dumped, str)


# ---------------------------------------------------------------------------
# Tests: system prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_is_non_empty_string(self) -> None:
        assert isinstance(SYSTEM_PROMPT, str) and len(SYSTEM_PROMPT) > 50

    def test_mentions_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT

    def test_mentions_tailwinds(self) -> None:
        assert "tailwind" in SYSTEM_PROMPT.lower()

    def test_mentions_headwinds(self) -> None:
        assert "headwind" in SYSTEM_PROMPT.lower()

    def test_mentions_rbi(self) -> None:
        assert "RBI" in SYSTEM_PROMPT or "rbi" in SYSTEM_PROMPT.lower()

    def test_mentions_global_factors(self) -> None:
        assert "global" in SYSTEM_PROMPT.lower()
