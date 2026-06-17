# backend/tests/unit/test_memo_generator.py
"""
Unit tests for T-042: Investment Memo Generator.

Test strategy:
  1. _non_empty                        -- fallback text helper
  2. _format_conviction_label          -- conviction score -> label
  3. _format_agent_weights_table       -- agent_weights dict -> Markdown
  4. _build_header_section             -- verdict/conviction/price/horizon
  5. _build_executive_summary_section  -- with and without content
  6. _build_thesis_section             -- plain-English verdict framing
  7. _build_bull_case_section          -- bull case + catalysts
  8. _build_bear_case_section          -- bear case + contrarian response
  9. _build_risk_section               -- risk summary + key risks
 10. _build_valuation_section          -- valuation summary + price target
 11. _build_recommendation_section     -- final verdict synthesis
 12. _build_memo_markdown              -- full assembly from a decision dict
 13. _build_no_decision_memo           -- fallback when decision is missing
 14. generate_investment_memo          -- LangGraph node: state in -> state out
 15. Acceptance criteria               -- TCS end-to-end, all sections
                                          populated, readable by a
                                          non-technical person

Acceptance criteria verified (from task spec):
  * Memo generated for TCS
  * All sections populated
  * Readable by a non-technical person (plain-English verdict framing
    present, no raw field names or jargon-only output, disclaimer
    included)

No LLM calls, no network, no database. This module is pure formatting
logic over an already-computed InvestmentDecision dict.
"""
from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("ENVIRONMENT", "test")

from backend.services.memo_generator import (  # noqa: E402
    _build_bear_case_section,
    _build_bull_case_section,
    _build_executive_summary_section,
    _build_header_section,
    _build_memo_markdown,
    _build_no_decision_memo,
    _build_recommendation_section,
    _build_risk_section,
    _build_thesis_section,
    _build_valuation_section,
    _format_agent_weights_table,
    _format_conviction_label,
    _non_empty,
    generate_investment_memo,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_TCS_DECISION: dict[str, Any] = {
    "agent_name": "portfolio_manager",
    "analysis_id": "test-job-tcs-001",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "verdict": "BUY",
    "conviction_score": 8,
    "price_target": "Rs. 4,500 (12 months)",
    "time_horizon": "12 months",
    "executive_summary": (
        "TCS demonstrates exceptional fundamental quality with a 46.2% "
        "ROE and a net-cash balance sheet. The committee recommends a "
        "BUY with high conviction."
    ),
    "investment_thesis": (
        "The bull case rests on strong ROE, though Round 1 of the "
        "debate raised customer concentration as a tempering factor. "
        "The committee weighed this against the broader weight of "
        "evidence and proceeded with a BUY."
    ),
    "bull_case": (
        "Fundamental score of 9/10 driven by 46.2% ROE and consistent "
        "double-digit revenue growth over the trailing 4 years."
    ),
    "bear_case": (
        "Customer concentration in the top 5 clients exceeds 40% per "
        "the Contrarian's analysis, a structural risk not captured by "
        "standard fundamental scoring."
    ),
    "risk_summary": (
        "Risk score of 3/10; no critical governance or regulatory "
        "flags identified by the Risk Officer."
    ),
    "valuation_summary": (
        "DCF implies 18.4% upside to intrinsic value versus the "
        "current trading price."
    ),
    "key_risks": [
        "Customer concentration in top 5 clients exceeds 40%",
        "High trailing PE of 28.5x limits near-term upside",
    ],
    "key_catalysts": [
        "INR depreciation benefits IT exporters",
        "Strong deal pipeline reported in latest earnings call",
    ],
    "contrarian_response": (
        "Addressing the Contrarian's strongest argument on customer "
        "concentration: the committee weighs this against the low "
        "overall risk score and assigns high conviction."
    ),
    "debate_rounds_used": 1,
    "agent_weights": {
        "fundamental_analyst": 0.2,
        "valuation_agent": 0.2,
        "risk_officer": 0.15,
        "contrarian_investor": 0.15,
        "technical_analyst": 0.12,
        "macro_economist": 0.1,
        "news_sentiment": 0.08,
    },
    "summary": "TCS: BUY with conviction 8/10.",
    "error": None,
}

_SELL_DECISION: dict[str, Any] = {
    **_TCS_DECISION,
    "verdict": "SELL",
    "conviction_score": 7,
    "price_target": None,
    "summary": "Risky Corp: SELL with conviction 7/10.",
}

_HOLD_DECISION: dict[str, Any] = {
    **_TCS_DECISION,
    "verdict": "HOLD",
    "conviction_score": 5,
    "time_horizon": "quarterly review (3 months)",
    "summary": "Mixed Corp: HOLD with conviction 5/10.",
}

_MINIMAL_DECISION: dict[str, Any] = {
    "verdict": "HOLD",
    "conviction_score": 1,
    "error": "ticker field is missing from InvestmentState",
}


# ---------------------------------------------------------------------------
# Tests: _non_empty
# ---------------------------------------------------------------------------


class TestNonEmpty:
    def test_returns_text_when_present(self) -> None:
        assert _non_empty("Some content") == "Some content"

    def test_strips_whitespace(self) -> None:
        assert _non_empty("  padded  ") == "padded"

    def test_returns_fallback_when_none(self) -> None:
        result = _non_empty(None)
        assert "not available" in result.lower()

    def test_returns_fallback_when_empty_string(self) -> None:
        result = _non_empty("")
        assert "not available" in result.lower()

    def test_returns_fallback_when_whitespace_only(self) -> None:
        result = _non_empty("   ")
        assert "not available" in result.lower()

    def test_custom_fallback_used(self) -> None:
        result = _non_empty(None, fallback="custom fallback text")
        assert result == "custom fallback text"


# ---------------------------------------------------------------------------
# Tests: _format_conviction_label
# ---------------------------------------------------------------------------


class TestFormatConvictionLabel:
    def test_high_conviction_label(self) -> None:
        assert "high conviction" in _format_conviction_label(8)
        assert "high conviction" in _format_conviction_label(10)

    def test_moderate_conviction_label(self) -> None:
        assert "moderate conviction" in _format_conviction_label(5)
        assert "moderate conviction" in _format_conviction_label(7)

    def test_low_conviction_label(self) -> None:
        assert "low conviction" in _format_conviction_label(1)
        assert "low conviction" in _format_conviction_label(4)

    def test_includes_numeric_score(self) -> None:
        assert "8/10" in _format_conviction_label(8)


# ---------------------------------------------------------------------------
# Tests: _format_agent_weights_table
# ---------------------------------------------------------------------------


class TestFormatAgentWeightsTable:
    def test_renders_markdown_table(self) -> None:
        table = _format_agent_weights_table(_TCS_DECISION["agent_weights"])
        assert "| Committee Member | Weight |" in table
        assert "Fundamental Analyst" in table
        assert "40%" not in table  # sanity: not garbled
        assert "20%" in table

    def test_empty_weights_returns_explanatory_text(self) -> None:
        table = _format_agent_weights_table({})
        assert "not available" in table.lower()

    def test_all_zero_weights_returns_explanatory_text(self) -> None:
        table = _format_agent_weights_table(
            {"fundamental_analyst": 0.0, "technical_analyst": 0.0}
        )
        assert "not available" in table.lower()

    def test_all_seven_agents_present_in_table(self) -> None:
        table = _format_agent_weights_table(_TCS_DECISION["agent_weights"])
        for label in (
            "Fundamental Analyst",
            "Technical Analyst",
            "News Sentiment Agent",
            "Macro Economist",
            "Risk Officer",
            "Contrarian Investor",
            "Valuation Agent",
        ):
            assert label in table


# ---------------------------------------------------------------------------
# Tests: _build_header_section
# ---------------------------------------------------------------------------


class TestBuildHeaderSection:
    def _build(self, **overrides: Any) -> str:
        defaults: dict[str, Any] = {
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "verdict": "BUY",
            "conviction_score": 8,
            "price_target": "Rs. 4,500 (12 months)",
            "time_horizon": "12 months",
            "generated_at": "17 Jun 2026, 10:00 UTC",
        }
        defaults.update(overrides)
        return _build_header_section(**defaults)

    def test_contains_company_and_ticker(self) -> None:
        header = self._build()
        assert "Tata Consultancy Services" in header
        assert "TCS.NS" in header

    def test_contains_verdict(self) -> None:
        header = self._build()
        assert "BUY" in header

    def test_contains_price_target(self) -> None:
        header = self._build()
        assert "Rs. 4,500" in header

    def test_missing_price_target_shows_not_available(self) -> None:
        header = self._build(price_target=None)
        assert "Not available" in header

    def test_contains_generated_timestamp(self) -> None:
        header = self._build()
        assert "17 Jun 2026" in header

    def test_is_markdown_h1(self) -> None:
        header = self._build()
        assert header.startswith("# Investment Memo:")


# ---------------------------------------------------------------------------
# Tests: _build_executive_summary_section
# ---------------------------------------------------------------------------


class TestBuildExecutiveSummarySection:
    def test_contains_provided_summary(self) -> None:
        section = _build_executive_summary_section("A detailed summary.")
        assert "A detailed summary." in section

    def test_empty_summary_uses_fallback(self) -> None:
        section = _build_executive_summary_section("")
        assert "could not be generated" in section.lower()

    def test_has_section_header(self) -> None:
        section = _build_executive_summary_section("Summary text.")
        assert "Executive Summary" in section


# ---------------------------------------------------------------------------
# Tests: _build_thesis_section
# ---------------------------------------------------------------------------


class TestBuildThesisSection:
    def test_buy_includes_plain_english_framing(self) -> None:
        section = _build_thesis_section("BUY", "Thesis text here.")
        assert "recommends buying" in section.lower()

    def test_sell_includes_plain_english_framing(self) -> None:
        section = _build_thesis_section("SELL", "Thesis text here.")
        assert "recommends against buying" in section.lower()

    def test_hold_includes_plain_english_framing(self) -> None:
        section = _build_thesis_section("HOLD", "Thesis text here.")
        assert "holding off" in section.lower()

    def test_contains_provided_thesis(self) -> None:
        section = _build_thesis_section("BUY", "A specific debate-grounded thesis.")
        assert "A specific debate-grounded thesis." in section


# ---------------------------------------------------------------------------
# Tests: _build_bull_case_section
# ---------------------------------------------------------------------------


class TestBuildBullCaseSection:
    def test_contains_bull_case_text(self) -> None:
        section = _build_bull_case_section("Strong fundamentals.", [])
        assert "Strong fundamentals." in section

    def test_contains_catalysts_when_present(self) -> None:
        section = _build_bull_case_section(
            "Strong fundamentals.", ["Catalyst A", "Catalyst B"]
        )
        assert "Catalyst A" in section
        assert "Catalyst B" in section

    def test_no_catalyst_subsection_when_empty(self) -> None:
        section = _build_bull_case_section("Strong fundamentals.", [])
        assert "Potential catalysts" not in section


# ---------------------------------------------------------------------------
# Tests: _build_bear_case_section
# ---------------------------------------------------------------------------


class TestBuildBearCaseSection:
    def test_contains_bear_case_text(self) -> None:
        section = _build_bear_case_section("Concentration risk.", "Addressed directly.")
        assert "Concentration risk." in section

    def test_contains_contrarian_response(self) -> None:
        section = _build_bear_case_section("Concentration risk.", "Addressed directly.")
        assert "Addressed directly." in section

    def test_empty_contrarian_response_uses_fallback(self) -> None:
        section = _build_bear_case_section("Concentration risk.", "")
        assert "considered alongside" in section.lower()


# ---------------------------------------------------------------------------
# Tests: _build_risk_section
# ---------------------------------------------------------------------------


class TestBuildRiskSection:
    def test_contains_risk_summary(self) -> None:
        section = _build_risk_section("Low risk overall.", [])
        assert "Low risk overall." in section

    def test_contains_numbered_key_risks(self) -> None:
        section = _build_risk_section("Low risk overall.", ["Risk A", "Risk B"])
        assert "1. Risk A" in section
        assert "2. Risk B" in section

    def test_no_risk_list_subsection_when_empty(self) -> None:
        section = _build_risk_section("Low risk overall.", [])
        assert "Key risks to monitor" not in section


# ---------------------------------------------------------------------------
# Tests: _build_valuation_section
# ---------------------------------------------------------------------------


class TestBuildValuationSection:
    def test_contains_valuation_summary(self) -> None:
        section = _build_valuation_section("Undervalued by 18%.", "Rs. 4,500")
        assert "Undervalued by 18%." in section

    def test_contains_price_target_when_present(self) -> None:
        section = _build_valuation_section("Undervalued by 18%.", "Rs. 4,500")
        assert "Rs. 4,500" in section

    def test_no_price_target_line_when_none(self) -> None:
        section = _build_valuation_section("Fairly valued.", None)
        assert "Implied price target" not in section


# ---------------------------------------------------------------------------
# Tests: _build_recommendation_section
# ---------------------------------------------------------------------------


class TestBuildRecommendationSection:
    def _build(self, **overrides: Any) -> str:
        defaults: dict[str, Any] = {
            "verdict": "BUY",
            "conviction_score": 8,
            "time_horizon": "12 months",
            "summary": "TCS: BUY with conviction 8/10.",
            "agent_weights": _TCS_DECISION["agent_weights"],
            "debate_rounds_used": 1,
        }
        defaults.update(overrides)
        return _build_recommendation_section(**defaults)

    def test_contains_verdict(self) -> None:
        section = self._build()
        assert "BUY" in section

    def test_contains_summary(self) -> None:
        section = self._build()
        assert "TCS: BUY with conviction 8/10." in section

    def test_contains_time_horizon(self) -> None:
        section = self._build()
        assert "12 months" in section

    def test_singular_round_text(self) -> None:
        section = self._build(debate_rounds_used=1)
        assert "1 round of" in section

    def test_plural_rounds_text(self) -> None:
        section = self._build(debate_rounds_used=2)
        assert "2 rounds of" in section

    def test_contains_agent_weights_table(self) -> None:
        section = self._build()
        assert "Committee Member" in section


# ---------------------------------------------------------------------------
# Tests: _build_memo_markdown (full assembly)
# ---------------------------------------------------------------------------


class TestBuildMemoMarkdown:
    def test_returns_non_empty_string(self) -> None:
        memo = _build_memo_markdown(
            "Tata Consultancy Services", "TCS.NS", _TCS_DECISION, "17 Jun 2026"
        )
        assert isinstance(memo, str)
        assert len(memo) > 0

    def test_contains_all_seven_required_sections(self) -> None:
        """
        Acceptance criterion: all sections populated. Verifies the
        7 sections named in the task description are all present.
        """
        memo = _build_memo_markdown(
            "Tata Consultancy Services", "TCS.NS", _TCS_DECISION, "17 Jun 2026"
        )
        for heading in (
            "Executive Summary",
            "Investment Thesis",
            "Bull Case",
            "Bear Case",
            "Risk Analysis",
            "Valuation",
            "Recommendation",
        ):
            assert heading in memo, f"Missing section: {heading}"

    def test_contains_disclaimer(self) -> None:
        memo = _build_memo_markdown(
            "Tata Consultancy Services", "TCS.NS", _TCS_DECISION, "17 Jun 2026"
        )
        assert "not financial advice" in memo.lower()

    def test_buy_decision_renders_correctly(self) -> None:
        memo = _build_memo_markdown("TCS", "TCS.NS", _TCS_DECISION, "17 Jun 2026")
        assert "BUY" in memo

    def test_sell_decision_renders_correctly(self) -> None:
        memo = _build_memo_markdown(
            "Risky Corp", "RISK.NS", _SELL_DECISION, "17 Jun 2026"
        )
        assert "SELL" in memo

    def test_hold_decision_renders_correctly(self) -> None:
        memo = _build_memo_markdown(
            "Mixed Corp", "MIX.NS", _HOLD_DECISION, "17 Jun 2026"
        )
        assert "HOLD" in memo

    def test_minimal_decision_does_not_raise(self) -> None:
        """A decision with almost nothing populated must still render."""
        memo = _build_memo_markdown(
            "Test Corp", "TEST.NS", _MINIMAL_DECISION, "17 Jun 2026"
        )
        assert isinstance(memo, str)
        assert len(memo) > 0

    def test_readable_by_non_technical_reader(self) -> None:
        """
        Acceptance criterion: readable by a non-technical person.
        Checks plain-English framing is present and no raw Python/JSON
        artifacts leak into the rendered text.
        """
        memo = _build_memo_markdown(
            "Tata Consultancy Services", "TCS.NS", _TCS_DECISION, "17 Jun 2026"
        )
        assert "recommends buying" in memo.lower()
        assert "{" not in memo
        assert "None" not in memo or "Not available" in memo

    def test_key_risks_appear_as_numbered_list(self) -> None:
        memo = _build_memo_markdown("TCS", "TCS.NS", _TCS_DECISION, "17 Jun 2026")
        assert "1. Customer concentration" in memo

    def test_key_catalysts_appear_as_bullets(self) -> None:
        memo = _build_memo_markdown("TCS", "TCS.NS", _TCS_DECISION, "17 Jun 2026")
        assert "- INR depreciation benefits IT exporters" in memo


# ---------------------------------------------------------------------------
# Tests: _build_no_decision_memo
# ---------------------------------------------------------------------------


class TestBuildNoDecisionMemo:
    def test_returns_non_empty_string(self) -> None:
        memo = _build_no_decision_memo("Test Corp", "TEST.NS", "17 Jun 2026")
        assert isinstance(memo, str)
        assert len(memo) > 0

    def test_contains_company_and_ticker(self) -> None:
        memo = _build_no_decision_memo("Test Corp", "TEST.NS", "17 Jun 2026")
        assert "Test Corp" in memo
        assert "TEST.NS" in memo

    def test_contains_incomplete_notice(self) -> None:
        memo = _build_no_decision_memo("Test Corp", "TEST.NS", "17 Jun 2026")
        assert "could not be completed" in memo.lower()

    def test_contains_disclaimer(self) -> None:
        memo = _build_no_decision_memo("Test Corp", "TEST.NS", "17 Jun 2026")
        assert "not financial advice" in memo.lower()


# ---------------------------------------------------------------------------
# Tests: generate_investment_memo (LangGraph node)
# ---------------------------------------------------------------------------


class TestGenerateInvestmentMemoNode:
    def test_returns_dict_with_memo_markdown_key(self) -> None:
        state = {
            "job_id": "test-job-001",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "decision": _TCS_DECISION,
        }
        result = generate_investment_memo(state)
        assert "memo_markdown" in result
        assert isinstance(result["memo_markdown"], str)

    def test_tcs_end_to_end_memo_generation(self) -> None:
        """
        Primary acceptance criterion: memo generated for TCS, all
        sections populated, end to end through the node entry point.
        """
        state = {
            "job_id": "test-job-tcs",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "decision": _TCS_DECISION,
        }
        result = generate_investment_memo(state)
        memo = result["memo_markdown"]
        assert "Tata Consultancy Services" in memo
        assert "TCS.NS" in memo
        for heading in (
            "Executive Summary",
            "Investment Thesis",
            "Bull Case",
            "Bear Case",
            "Risk Analysis",
            "Valuation",
            "Recommendation",
        ):
            assert heading in memo

    def test_missing_decision_returns_fallback_memo(self) -> None:
        state = {
            "job_id": "test-job-no-decision",
            "company_name": "Test Corp",
            "ticker": "TEST.NS",
        }
        result = generate_investment_memo(state)
        assert "could not be completed" in result["memo_markdown"].lower()

    def test_none_decision_returns_fallback_memo(self) -> None:
        state = {
            "job_id": "test-job-none",
            "company_name": "Test Corp",
            "ticker": "TEST.NS",
            "decision": None,
        }
        result = generate_investment_memo(state)
        assert "could not be completed" in result["memo_markdown"].lower()

    def test_missing_company_name_uses_fallback(self) -> None:
        state: dict[str, Any] = {"job_id": "test-job", "decision": _TCS_DECISION}
        result = generate_investment_memo(state)
        assert isinstance(result["memo_markdown"], str)
        assert len(result["memo_markdown"]) > 0

    def test_never_raises_on_malformed_decision(self) -> None:
        """Agent contract: never raises, even on garbage input."""
        state: dict[str, Any] = {
            "job_id": "test-job",
            "company_name": "Test Corp",
            "ticker": "TEST.NS",
            "decision": {"verdict": None, "agent_weights": "not-a-dict"},
        }
        result = generate_investment_memo(state)
        assert "memo_markdown" in result
        assert isinstance(result["memo_markdown"], str)

    def test_result_does_not_mutate_input_state(self) -> None:
        state = {
            "job_id": "test-job",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "decision": _TCS_DECISION,
        }
        original_keys = set(state.keys())
        generate_investment_memo(state)
        assert set(state.keys()) == original_keys

    def test_result_only_contains_memo_markdown_key(self) -> None:
        """The node returns a partial-state dict -- exactly one new key."""
        state = {
            "job_id": "test-job",
            "company_name": "Tata Consultancy Services",
            "ticker": "TCS.NS",
            "decision": _TCS_DECISION,
        }
        result = generate_investment_memo(state)
        assert list(result.keys()) == ["memo_markdown"]
