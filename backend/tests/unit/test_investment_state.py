# backend/tests/unit/test_investment_state.py
"""
Unit tests for T-029: InvestmentState TypedDict.

Acceptance criteria (from project plan):
  - State roundtrips through JSON serialisation
  - All fields typed
  - Documented in docs/STATE.md

Test strategy
-------------
  1. make_initial_state   -- factory produces required fields with correct types
  2. Optional fields      -- absent by default, settable when provided
  3. JSON round-trip      -- state_to_json / state_from_json round-trip is lossless
  4. Partial state        -- partially-populated state survives round-trip
  5. Fully-populated      -- all fields set, round-trip still works
  6. Agent output dicts   -- model.model_dump() dicts are JSON-safe in state
  7. Debate rounds        -- list of dicts survives serialisation
  8. Risk flags           -- list fields initialised to empty and appendable
  9. Version field        -- always 1 on initial state
 10. state_from_json      -- returns a dict with expected keys
 11. Edge cases           -- empty string fields, zero counts, None optionals

All tests are pure unit tests: no I/O, no database, no LLM calls.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

from backend.agents.output_models import (  # noqa: E402
    ContrarianReport,
    FundamentalAnalysis,
    InvestmentDecision,
    MacroAnalysis,
    RiskAnalysis,
    SentimentAnalysis,
    TechnicalAnalysis,
    ValuationOutput,
)
from backend.graph.state import (  # noqa: E402
    DebateRound,
    InvestmentState,
    make_initial_state,
    state_from_json,
    state_to_json,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t029-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_EXCHANGE = "NSE"
_RAW_QUERY = "TCS"

_BASE_AGENT_KWARGS: dict[str, Any] = {
    "analysis_id": _JOB_ID,
    "company_name": _COMPANY,
    "ticker": _TICKER,
}


def _make_state(**overrides: Any) -> InvestmentState:
    """Return a minimal initial state with optional overrides."""
    state = make_initial_state(
        job_id=_JOB_ID,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange=_EXCHANGE,
        raw_query=_RAW_QUERY,
    )
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def _round_trip(state: InvestmentState) -> InvestmentState:
    """Serialise then deserialise state."""
    return state_from_json(state_to_json(state))


# ---------------------------------------------------------------------------
# 1. make_initial_state -- required fields
# ---------------------------------------------------------------------------


class TestMakeInitialState:
    """Factory function produces a correctly shaped minimal state."""

    def test_job_id_set(self) -> None:
        state = _make_state()
        assert state["job_id"] == _JOB_ID

    def test_company_name_set(self) -> None:
        state = _make_state()
        assert state["company_name"] == _COMPANY

    def test_ticker_set(self) -> None:
        state = _make_state()
        assert state["ticker"] == _TICKER

    def test_exchange_set(self) -> None:
        state = _make_state()
        assert state["exchange"] == _EXCHANGE

    def test_raw_query_set(self) -> None:
        state = _make_state()
        assert state["raw_query"] == _RAW_QUERY

    def test_status_is_pending(self) -> None:
        state = _make_state()
        assert state["status"] == "pending"

    def test_version_is_one(self) -> None:
        state = _make_state()
        assert state["version"] == 1

    def test_debate_round_count_zero(self) -> None:
        state = _make_state()
        assert state["debate_round_count"] == 0

    def test_debate_rounds_empty_list(self) -> None:
        state = _make_state()
        assert state["debate_rounds"] == []

    def test_risk_flags_empty_list(self) -> None:
        state = _make_state()
        assert state["risk_flags"] == []

    def test_critical_flags_empty_list(self) -> None:
        state = _make_state()
        assert state["critical_flags"] == []

    def test_langsmith_run_ids_empty_dict(self) -> None:
        state = _make_state()
        assert state["langsmith_run_ids"] == {}

    def test_requested_by_defaults_to_anonymous(self) -> None:
        state = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query=_RAW_QUERY,
        )
        assert state["requested_by"] == "anonymous"

    def test_requested_by_custom(self) -> None:
        state = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query=_RAW_QUERY,
            requested_by="user_abc123",
        )
        assert state["requested_by"] == "user_abc123"

    def test_requested_at_is_iso_string(self) -> None:
        state = _make_state()
        ts = state["requested_at"]
        assert isinstance(ts, str)
        # Should be parseable as ISO datetime
        # Remove trailing Z for fromisoformat compatibility
        datetime.fromisoformat(ts.rstrip("Z"))

    def test_is_dict_subtype(self) -> None:
        """InvestmentState must behave as a plain dict for LangGraph."""
        state = _make_state()
        assert isinstance(state, dict)


# ---------------------------------------------------------------------------
# 2. Optional fields -- absent by default, settable when provided
# ---------------------------------------------------------------------------


class TestOptionalFields:
    """Optional fields are absent (not None) until explicitly set."""

    def test_isin_absent_by_default(self) -> None:
        state = _make_state()
        assert "isin" not in state

    def test_sector_absent_by_default(self) -> None:
        state = _make_state()
        assert "sector" not in state

    def test_industry_absent_by_default(self) -> None:
        state = _make_state()
        assert "industry" not in state

    def test_isin_set_when_provided(self) -> None:
        state = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query=_RAW_QUERY,
            isin="INE467B01029",
        )
        assert state["isin"] == "INE467B01029"

    def test_sector_set_when_provided(self) -> None:
        state = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query=_RAW_QUERY,
            sector="Information Technology",
        )
        assert state["sector"] == "Information Technology"

    def test_fundamental_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("fundamental") is None

    def test_technical_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("technical") is None

    def test_sentiment_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("sentiment") is None

    def test_macro_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("macro") is None

    def test_risk_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("risk") is None

    def test_contrarian_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("contrarian") is None

    def test_valuation_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("valuation") is None

    def test_decision_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("decision") is None

    def test_final_verdict_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("final_verdict") is None

    def test_conviction_score_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("conviction_score") is None

    def test_memo_markdown_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("memo_markdown") is None

    def test_pipeline_error_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("pipeline_error") is None


# ---------------------------------------------------------------------------
# 3. JSON round-trip -- state_to_json / state_from_json
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    """state_to_json / state_from_json must be lossless."""

    def test_minimal_state_round_trips(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        assert recovered["job_id"] == state["job_id"]
        assert recovered["company_name"] == state["company_name"]
        assert recovered["ticker"] == state["ticker"]
        assert recovered["exchange"] == state["exchange"]
        assert recovered["version"] == state["version"]

    def test_state_to_json_returns_string(self) -> None:
        state = _make_state()
        result = state_to_json(state)
        assert isinstance(result, str)

    def test_state_to_json_is_valid_json(self) -> None:
        state = _make_state()
        parsed = json.loads(state_to_json(state))
        assert isinstance(parsed, dict)

    def test_state_from_json_returns_dict(self) -> None:
        state = _make_state()
        recovered = state_from_json(state_to_json(state))
        assert isinstance(recovered, dict)

    def test_round_trip_preserves_status(self) -> None:
        state = _make_state()
        state["status"] = "running"
        recovered = _round_trip(state)
        assert recovered["status"] == "running"

    def test_round_trip_preserves_debate_round_count(self) -> None:
        state = _make_state()
        state["debate_round_count"] = 2
        recovered = _round_trip(state)
        assert recovered["debate_round_count"] == 2

    def test_round_trip_preserves_risk_flags(self) -> None:
        state = _make_state()
        state["risk_flags"] = ["High promoter pledge", "SEBI notice pending"]
        recovered = _round_trip(state)
        assert recovered["risk_flags"] == [
            "High promoter pledge",
            "SEBI notice pending",
        ]

    def test_round_trip_preserves_langsmith_run_ids(self) -> None:
        state = _make_state()
        state["langsmith_run_ids"] = {"fundamental_analyst": "ls-run-abc123"}
        recovered = _round_trip(state)
        assert recovered["langsmith_run_ids"]["fundamental_analyst"] == "ls-run-abc123"

    def test_round_trip_with_none_optional(self) -> None:
        state = _make_state()
        state["pipeline_error"] = None
        recovered = _round_trip(state)
        assert recovered.get("pipeline_error") is None

    def test_round_trip_with_string_optional(self) -> None:
        state = _make_state()
        state["final_verdict"] = "BUY"
        recovered = _round_trip(state)
        assert recovered["final_verdict"] == "BUY"

    def test_round_trip_preserves_version(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        assert recovered["version"] == 1


# ---------------------------------------------------------------------------
# 4. Partial state -- partially-populated state survives round-trip
# ---------------------------------------------------------------------------


class TestPartialStateRoundTrip:
    """Only identity fields set -- rest absent -- still round-trips."""

    def test_partial_state_has_correct_keys(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        assert "job_id" in recovered
        assert "company_name" in recovered
        assert "ticker" in recovered

    def test_partial_state_missing_agent_fields(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        # Agent fields not yet populated should be absent
        assert "fundamental" not in recovered or recovered.get("fundamental") is None
        assert "technical" not in recovered or recovered.get("technical") is None


# ---------------------------------------------------------------------------
# 5. Fully-populated state -- all fields set, round-trip works
# ---------------------------------------------------------------------------


class TestFullyPopulatedStateRoundTrip:
    """A state with all fields populated must survive JSON round-trip."""

    def _make_full_state(self) -> InvestmentState:
        """Build a maximally populated state."""
        state = _make_state()
        state["status"] = "completed"
        state["current_node"] = "portfolio_manager"
        state["started_at"] = "2024-01-15T10:00:00Z"
        state["completed_at"] = "2024-01-15T10:01:30Z"
        state["debate_round_count"] = 2
        state["debate_rounds"] = [
            {
                "round_number": 1,
                "agent_responses": {"fundamental_analyst": "Strong buy."},
                "contrarian": "FCF declining 3 years.",
                "completed_at": "2024-01-15T10:00:45Z",
            },
            {
                "round_number": 2,
                "agent_responses": {"fundamental_analyst": "Addressed: one-off capex."},
                "contrarian": "Margin pressure persists.",
                "completed_at": "2024-01-15T10:01:15Z",
            },
        ]
        state["risk_flags"] = ["High D/E ratio", "Promoter pledge 30%"]
        state["critical_flags"] = ["Promoter pledge 30%"]
        state["final_verdict"] = "BUY"
        state["conviction_score"] = 8
        state["price_target"] = "Rs 4,200 (12-month)"
        state["memo_markdown"] = (
            "# TCS Investment Memo\n\n**BUY** with 8/10 conviction."
        )
        state["memo_pdf_path"] = "/outputs/t029-test-job-uuid-001.pdf"
        state["isin"] = "INE467B01029"
        state["sector"] = "Information Technology"
        state["industry"] = "IT Services & Consulting"
        state["langsmith_run_ids"] = {
            "fundamental_analyst": "ls-run-fa-001",
            "technical_analyst": "ls-run-ta-001",
        }
        return state

    def test_full_state_round_trips(self) -> None:
        state = self._make_full_state()
        recovered = _round_trip(state)
        assert recovered["final_verdict"] == "BUY"
        assert recovered["conviction_score"] == 8
        assert recovered["debate_round_count"] == 2
        assert len(recovered["debate_rounds"]) == 2
        assert recovered["status"] == "completed"

    def test_full_state_json_is_valid(self) -> None:
        state = self._make_full_state()
        json_str = state_to_json(state)
        parsed = json.loads(json_str)
        assert parsed["final_verdict"] == "BUY"
        assert parsed["version"] == 1

    def test_full_state_memo_preserved(self) -> None:
        state = self._make_full_state()
        recovered = _round_trip(state)
        assert recovered["memo_markdown"] is not None
        assert "TCS Investment Memo" in str(recovered["memo_markdown"])

    def test_debate_rounds_preserved(self) -> None:
        state = self._make_full_state()
        recovered = _round_trip(state)
        rounds = recovered["debate_rounds"]
        assert isinstance(rounds, list)
        assert len(rounds) == 2
        assert rounds[0]["round_number"] == 1
        assert rounds[1]["round_number"] == 2


# ---------------------------------------------------------------------------
# 6. Agent output dicts -- model.model_dump() dicts are JSON-safe in state
# ---------------------------------------------------------------------------


class TestAgentOutputDictsInState:
    """Agent output model_dump() dicts survive state serialisation."""

    def test_fundamental_model_dump_in_state(self) -> None:
        fa = FundamentalAnalysis(score=8, **_BASE_AGENT_KWARGS)
        state = _make_state()
        state["fundamental"] = fa.model_dump()
        recovered = _round_trip(state)
        assert recovered["fundamental"] is not None
        fund = recovered["fundamental"]
        assert isinstance(fund, dict)
        assert fund["score"] == 8
        assert fund["agent_name"] == "fundamental_analyst"

    def test_technical_model_dump_in_state(self) -> None:
        ta = TechnicalAnalysis(signal="BUY", signal_strength=7, **_BASE_AGENT_KWARGS)
        state = _make_state()
        state["technical"] = ta.model_dump()
        recovered = _round_trip(state)
        assert recovered["technical"] is not None
        tech = recovered["technical"]
        assert isinstance(tech, dict)
        assert tech["signal"] == "BUY"

    def test_sentiment_model_dump_in_state(self) -> None:
        sa = SentimentAnalysis(
            sentiment_score=0.5,
            sentiment_label="positive",
            articles_analysed=30,
            positive_articles=20,
            negative_articles=5,
            neutral_articles=5,
            **_BASE_AGENT_KWARGS,
        )
        state = _make_state()
        state["sentiment"] = sa.model_dump()
        recovered = _round_trip(state)
        assert recovered["sentiment"] is not None
        sent = recovered["sentiment"]
        assert isinstance(sent, dict)
        assert sent["sentiment_score"] == 0.5

    def test_macro_model_dump_in_state(self) -> None:
        ma = MacroAnalysis(
            macro_environment="favourable",
            sector_impact="tailwind",
            **_BASE_AGENT_KWARGS,
        )
        state = _make_state()
        state["macro"] = ma.model_dump()
        recovered = _round_trip(state)
        assert recovered["macro"] is not None
        mac = recovered["macro"]
        assert isinstance(mac, dict)
        assert mac["macro_environment"] == "favourable"

    def test_risk_model_dump_in_state(self) -> None:
        ra = RiskAnalysis(
            risk_score=4,
            governance_risk=3,
            regulatory_risk=4,
            financial_risk=3,
            concentration_risk=5,
            **_BASE_AGENT_KWARGS,
        )
        state = _make_state()
        state["risk"] = ra.model_dump()
        recovered = _round_trip(state)
        assert recovered["risk"] is not None
        risk = recovered["risk"]
        assert isinstance(risk, dict)
        assert risk["risk_score"] == 4

    def test_contrarian_model_dump_in_state(self) -> None:
        cr = ContrarianReport(bear_conviction=6, **_BASE_AGENT_KWARGS)
        state = _make_state()
        state["contrarian"] = cr.model_dump()
        recovered = _round_trip(state)
        assert recovered["contrarian"] is not None
        cont = recovered["contrarian"]
        assert isinstance(cont, dict)
        assert cont["bear_conviction"] == 6

    def test_valuation_model_dump_in_state(self) -> None:
        vo = ValuationOutput(valuation_verdict="undervalued", **_BASE_AGENT_KWARGS)
        state = _make_state()
        state["valuation"] = vo.model_dump()
        recovered = _round_trip(state)
        assert recovered["valuation"] is not None
        val = recovered["valuation"]
        assert isinstance(val, dict)
        assert val["valuation_verdict"] == "undervalued"

    def test_decision_model_dump_in_state(self) -> None:
        decision = InvestmentDecision(
            verdict="BUY",
            conviction_score=8,
            **_BASE_AGENT_KWARGS,
        )
        state = _make_state()
        state["decision"] = decision.model_dump()
        recovered = _round_trip(state)
        assert recovered["decision"] is not None
        dec = recovered["decision"]
        assert isinstance(dec, dict)
        assert dec["verdict"] == "BUY"
        assert dec["conviction_score"] == 8

    def test_all_eight_agents_in_one_state(self) -> None:
        """All 8 agent outputs in a single state still round-trips."""
        state = _make_state()
        state["fundamental"] = FundamentalAnalysis(
            score=8, **_BASE_AGENT_KWARGS
        ).model_dump()
        state["technical"] = TechnicalAnalysis(
            signal="HOLD", signal_strength=5, **_BASE_AGENT_KWARGS
        ).model_dump()
        state["sentiment"] = SentimentAnalysis(
            sentiment_score=-0.1,
            sentiment_label="neutral",
            articles_analysed=15,
            positive_articles=6,
            negative_articles=5,
            neutral_articles=4,
            **_BASE_AGENT_KWARGS,
        ).model_dump()
        state["macro"] = MacroAnalysis(
            macro_environment="neutral",
            sector_impact="neutral",
            **_BASE_AGENT_KWARGS,
        ).model_dump()
        state["risk"] = RiskAnalysis(
            risk_score=5,
            governance_risk=4,
            regulatory_risk=5,
            financial_risk=4,
            concentration_risk=6,
            **_BASE_AGENT_KWARGS,
        ).model_dump()
        state["contrarian"] = ContrarianReport(
            bear_conviction=4, **_BASE_AGENT_KWARGS
        ).model_dump()
        state["valuation"] = ValuationOutput(
            valuation_verdict="fairly_valued", **_BASE_AGENT_KWARGS
        ).model_dump()
        state["decision"] = InvestmentDecision(
            verdict="HOLD",
            conviction_score=5,
            **_BASE_AGENT_KWARGS,
        ).model_dump()

        recovered = _round_trip(state)
        assert recovered["fundamental"]["score"] == 8  # type: ignore[index]
        assert recovered["technical"]["signal"] == "HOLD"  # type: ignore[index]
        assert recovered["decision"]["verdict"] == "HOLD"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 7. Debate rounds -- list of dicts survives serialisation
# ---------------------------------------------------------------------------


class TestDebateRounds:
    """Debate transcript is stored as list[dict] and must round-trip."""

    def test_empty_debate_rounds_round_trips(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        assert recovered["debate_rounds"] == []

    def test_single_debate_round_round_trips(self) -> None:
        state = _make_state()
        state["debate_rounds"] = [
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental_analyst": "Revenue growing 12% YoY.",
                    "technical_analyst": "Golden cross confirmed.",
                },
                "contrarian": "Growth deceleration risk not priced in.",
                "completed_at": "2024-01-15T10:00:45Z",
            }
        ]
        state["debate_round_count"] = 1
        recovered = _round_trip(state)
        assert len(recovered["debate_rounds"]) == 1
        round_one = recovered["debate_rounds"][0]
        assert round_one["round_number"] == 1
        assert round_one["contrarian"] == "Growth deceleration risk not priced in."

    def test_two_debate_rounds_round_trip(self) -> None:
        state = _make_state()
        state["debate_rounds"] = [
            {
                "round_number": 1,
                "agent_responses": {"fundamental_analyst": "Strong FCF."},
                "contrarian": "FCF declining 3 years.",
                "completed_at": "2024-01-15T10:00:45Z",
            },
            {
                "round_number": 2,
                "agent_responses": {"fundamental_analyst": "One-off capex."},
                "contrarian": "Margin pressure persists.",
                "completed_at": "2024-01-15T10:01:15Z",
            },
        ]
        state["debate_round_count"] = 2
        recovered = _round_trip(state)
        assert len(recovered["debate_rounds"]) == 2
        assert recovered["debate_round_count"] == 2

    def test_debate_rounds_appendable(self) -> None:
        """Debate rounds list can be extended in-place."""
        state = _make_state()
        state["debate_rounds"].append(
            {
                "round_number": 1,
                "agent_responses": {},
                "contrarian": "Test",
                "completed_at": "2024-01-15T10:00:45Z",
            }
        )
        assert len(state["debate_rounds"]) == 1
        assert state["debate_round_count"] == 0  # count updated separately


# ---------------------------------------------------------------------------
# 8. Risk flags -- list fields initialised to empty and appendable
# ---------------------------------------------------------------------------


class TestRiskFlags:
    """risk_flags and critical_flags behave as mutable lists in state."""

    def test_risk_flags_appendable(self) -> None:
        state = _make_state()
        state["risk_flags"].append("High promoter pledge")
        assert state["risk_flags"] == ["High promoter pledge"]

    def test_critical_flags_appendable(self) -> None:
        state = _make_state()
        state["critical_flags"].append("SEBI notice")
        assert state["critical_flags"] == ["SEBI notice"]

    def test_risk_flags_survive_round_trip(self) -> None:
        state = _make_state()
        state["risk_flags"] = ["Flag A", "Flag B", "Flag C"]
        recovered = _round_trip(state)
        assert recovered["risk_flags"] == ["Flag A", "Flag B", "Flag C"]

    def test_critical_flags_subset_of_risk_flags(self) -> None:
        state = _make_state()
        state["risk_flags"] = ["Flag A", "Critical B"]
        state["critical_flags"] = ["Critical B"]
        recovered = _round_trip(state)
        assert "Critical B" in recovered["critical_flags"]
        assert "Critical B" in recovered["risk_flags"]


# ---------------------------------------------------------------------------
# 9. Version field
# ---------------------------------------------------------------------------


class TestVersionField:
    """version is always 1 on initial state."""

    def test_version_is_integer(self) -> None:
        state = _make_state()
        assert isinstance(state["version"], int)

    def test_version_is_one(self) -> None:
        state = _make_state()
        assert state["version"] == 1

    def test_version_survives_round_trip(self) -> None:
        state = _make_state()
        recovered = _round_trip(state)
        assert recovered["version"] == 1

    def test_version_can_be_updated(self) -> None:
        """Future-proofing: version field is writable."""
        state = _make_state()
        state["version"] = 2
        assert state["version"] == 2


# ---------------------------------------------------------------------------
# 10. state_from_json -- returns expected structure
# ---------------------------------------------------------------------------


class TestStateFromJson:
    """state_from_json produces a usable InvestmentState dict."""

    def test_from_json_returns_dict(self) -> None:
        state = _make_state()
        recovered = state_from_json(state_to_json(state))
        assert isinstance(recovered, dict)

    def test_from_json_has_job_id(self) -> None:
        state = _make_state()
        recovered = state_from_json(state_to_json(state))
        assert recovered["job_id"] == _JOB_ID

    def test_from_json_invalid_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            state_from_json("not valid json {{{")

    def test_from_json_non_object_raises(self) -> None:
        """JSON array instead of object must raise AssertionError."""
        with pytest.raises(AssertionError):
            state_from_json("[1, 2, 3]")

    def test_from_json_empty_object(self) -> None:
        """Empty JSON object is a valid (empty) state from deserialisation."""
        recovered = state_from_json("{}")
        assert isinstance(recovered, dict)


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty strings, zero counts, None optionals."""

    def test_empty_raw_query(self) -> None:
        state = make_initial_state(
            job_id=_JOB_ID,
            company_name=_COMPANY,
            ticker=_TICKER,
            exchange=_EXCHANGE,
            raw_query="",
        )
        assert state["raw_query"] == ""
        recovered = _round_trip(state)
        assert recovered["raw_query"] == ""

    def test_none_memo_pdf_path(self) -> None:
        state = _make_state()
        state["memo_pdf_path"] = None
        recovered = _round_trip(state)
        assert recovered.get("memo_pdf_path") is None

    def test_conviction_score_min(self) -> None:
        state = _make_state()
        state["conviction_score"] = 1
        recovered = _round_trip(state)
        assert recovered["conviction_score"] == 1

    def test_conviction_score_max(self) -> None:
        state = _make_state()
        state["conviction_score"] = 10
        recovered = _round_trip(state)
        assert recovered["conviction_score"] == 10

    def test_state_is_mutable(self) -> None:
        """InvestmentState is a dict and must be mutable (unlike frozen Pydantic)."""
        state = _make_state()
        state["status"] = "running"
        assert state["status"] == "running"
        state["status"] = "completed"
        assert state["status"] == "completed"

    def test_get_missing_field_returns_none(self) -> None:
        """dict.get() on absent optional fields returns None."""
        state = _make_state()
        assert state.get("fundamental") is None
        assert state.get("decision") is None
        assert state.get("pipeline_error") is None

    def test_json_with_datetime_object_in_agent_dict(self) -> None:
        """state_to_json must handle datetime objects via default=str."""
        state = _make_state()
        # Simulate an agent output dict that still has a datetime object
        # (before model_dump(mode='json') is called)
        state["fundamental"] = {
            "agent_name": "fundamental_analyst",
            "score": 8,
            "generated_at": datetime(2024, 1, 15, 10, 0, 0),
        }
        # Should not raise; datetime converted to string
        json_str = state_to_json(state)
        parsed = json.loads(json_str)
        assert "2024-01-15" in parsed["fundamental"]["generated_at"]

    def test_uploaded_doc_fields_absent_by_default(self) -> None:
        state = _make_state()
        assert state.get("uploaded_doc_collection") is None
        assert state.get("uploaded_doc_filename") is None
        assert state.get("uploaded_doc_chunk_count") is None

    def test_uploaded_doc_fields_set(self) -> None:
        state = _make_state()
        state["uploaded_doc_collection"] = "airp_documents"
        state["uploaded_doc_filename"] = "TCS_AR_2024.pdf"
        state["uploaded_doc_chunk_count"] = 142
        recovered = _round_trip(state)
        assert recovered["uploaded_doc_collection"] == "airp_documents"
        assert recovered["uploaded_doc_filename"] == "TCS_AR_2024.pdf"
        assert recovered["uploaded_doc_chunk_count"] == 142


# ---------------------------------------------------------------------------
# 12. DebateRound documentation class
# ---------------------------------------------------------------------------


class TestDebateRoundDocumentation:
    """DebateRound class is importable and serves as documentation."""

    def test_debate_round_importable(self) -> None:
        assert DebateRound is not None

    def test_debate_round_has_docstring(self) -> None:
        assert DebateRound.__doc__ is not None
        assert len(DebateRound.__doc__) > 20
