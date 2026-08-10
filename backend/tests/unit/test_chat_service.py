# backend/tests/unit/test_chat_service.py
"""
Unit tests for T-100: backend/services/chat_service.py's
build_memo_context and its section formatters.

Test strategy
-------------
1. build_memo_context() -- end to end, against one shared fixture
   analysis (_FIXTURE_STATE_SNAPSHOT below), mirroring the mocked
   AsyncSession pattern established in
   test_analysis_result_history_service.py (T-050) for
   get_analysis_result:
     no row for analysis_id                  -- returns None
     row belongs to a different user          -- returns None (never
       reveals whether the analysis exists to a non-owner)
     status='pending'/'running'/'failed'      -- raises
       AnalysisNotReadyError with .status set to the row's actual status
     status='completed', snapshot is NULL     -- raises
       AnalysisNotReadyError (defensive fallback)
     status='completed', snapshot has no 'decision' key -- same
       defensive fallback
     status='completed', psycopg2-style string snapshot -- parsed
       identically to the asyncpg-style dict snapshot
     status='completed', full fixture snapshot -- returns a
       MemoChatContext whose 7 agent sections + debate transcript +
       decision section all contain the fixture's actual data, and
       whose full_context property joins everything with headings
2. Per-agent section formatters (_format_fundamental_section, etc.) --
   tested directly (pure functions, no I/O -- same precedent as
   backend/db/session.py's _prepare_url/_build_database_url being
   tested directly in test_orm_models.py):
     missing / None input           -- a clear "no output available"
       fallback line, never a KeyError/AttributeError
     agent output with error set    -- a clear "agent reported an
       error" line, not a crash trying to read the (absent) metric
       fields
     fully populated agent output   -- every field's value appears
       somewhere in the rendered text
3. _format_debate_transcript_section -- empty/None rounds, a
   malformed (non-dict) round entry mixed in with valid ones, and a
   fully populated multi-round transcript.
4. _format_decision_section -- missing/None decision, a decision with
   error set, and a fully populated decision including agent_weights.

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching
test_analysis_result_history_service.py's established pattern.
ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from backend.services.analysis import AnalysisNotReadyError
from backend.services.chat_service import (
    AGENT_DISPLAY_NAMES,
    AGENT_STATE_KEYS,
    MemoChatContext,
    _format_contrarian_section,
    _format_debate_transcript_section,
    _format_decision_section,
    _format_fundamental_section,
    _format_macro_section,
    _format_risk_section,
    _format_sentiment_section,
    _format_technical_section,
    _format_valuation_section,
    build_memo_context,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_row(
    user_id: uuid.UUID,
    status: str = "completed",
    state_snapshot: Any = None,
) -> tuple[Any, ...]:
    """Build a fake asyncpg Row as a plain tuple -- indexable like the
    real Result row build_memo_context reads via row[0]..row[2]."""
    return (user_id, status, state_snapshot)


def _make_session_returning_row(row: Optional[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


_FIXTURE_FUNDAMENTAL: dict[str, Any] = {
    "agent_name": "fundamental_analyst",
    "score": 8,
    "data_quality": "high",
    "years_available": 4,
    "revenue_growth_pct": 12.5,
    "revenue_cagr_3y_pct": 10.2,
    "gross_margin_pct": 45.0,
    "operating_margin_pct": 24.5,
    "net_margin_pct": 18.3,
    "free_cash_flow_cr": 15230.0,
    "fcf_yield_pct": 3.8,
    "debt_to_equity": 0.05,
    "current_ratio": 2.4,
    "interest_coverage": 45.0,
    "roe_pct": 42.1,
    "roce_pct": 55.6,
    "strengths": ["Consistent revenue growth", "Strong balance sheet"],
    "weaknesses": ["Slowing deal wins in BFSI"],
    "summary": "TCS shows strong fundamentals with high-quality 4-year data.",
    "error": None,
}

_FIXTURE_TECHNICAL: dict[str, Any] = {
    "agent_name": "technical_analyst",
    "signal": "BUY",
    "signal_strength": 7,
    "current_price": 3850.0,
    "week_52_high": 4150.0,
    "week_52_low": 3300.0,
    "price_vs_52w_high_pct": -7.2,
    "ma_50d": 3800.0,
    "ma_200d": 3700.0,
    "price_above_ma50": True,
    "price_above_ma200": True,
    "golden_cross": True,
    "rsi_14": 58.0,
    "momentum_1m_pct": 2.1,
    "momentum_3m_pct": 5.4,
    "momentum_6m_pct": 8.9,
    "momentum_1y_pct": 14.2,
    "avg_volume_30d": 2500000.0,
    "volume_trend": "increasing",
    "support_levels": [3700.0, 3600.0],
    "resistance_levels": [4000.0, 4150.0],
    "summary": "Technical picture is bullish with a golden cross intact.",
    "error": None,
}

_FIXTURE_SENTIMENT: dict[str, Any] = {
    "agent_name": "news_sentiment",
    "sentiment_score": 0.42,
    "sentiment_label": "positive",
    "articles_analysed": 40,
    "positive_articles": 24,
    "negative_articles": 6,
    "neutral_articles": 10,
    "red_flags": [],
    "red_flag_count": 0,
    "top_positive_headlines": ["TCS wins large deal with European bank"],
    "top_negative_headlines": ["Attrition ticks up in Q1"],
    "dominant_topics": ["deal wins", "hiring", "AI investments"],
    "summary": "News sentiment is broadly positive with no red flags.",
    "error": None,
}

_FIXTURE_MACRO: dict[str, Any] = {
    "agent_name": "macro_economist",
    "macro_environment": "stable",
    "sector_impact": "tailwind",
    "rbi_repo_rate_pct": 6.5,
    "rate_stance": "neutral",
    "rate_direction": "steady",
    "cpi_inflation_pct": 4.8,
    "wpi_inflation_pct": 2.1,
    "inflation_trend": "cooling",
    "gdp_growth_pct": 6.8,
    "gdp_forecast_pct": 7.0,
    "tailwinds": ["Resilient domestic demand"],
    "headwinds": ["Global IT spend uncertainty"],
    "usd_inr_rate": 83.2,
    "inr_trend": "stable",
    "summary": "Macro backdrop is supportive for IT services exporters.",
    "error": None,
}

_FIXTURE_RISK: dict[str, Any] = {
    "agent_name": "risk_officer",
    "risk_score": 3,
    "governance_risk": 2,
    "regulatory_risk": 2,
    "financial_risk": 1,
    "concentration_risk": 4,
    "risk_flags": ["High revenue concentration in BFSI vertical"],
    "critical_flags": [],
    "risk_recommendation": "Monitor BFSI client concentration quarterly.",
    "summary": "Overall risk is low; concentration is the main watch item.",
    "error": None,
}

_FIXTURE_CONTRARIAN: dict[str, Any] = {
    "agent_name": "contrarian_investor",
    "counter_arguments": ["Margins may compress if wage inflation accelerates"],
    "challenged_agents": ["fundamental_analyst", "valuation_agent"],
    "overlooked_risks": ["AI-driven pricing pressure on legacy contracts"],
    "bear_conviction": 4,
    "strongest_argument": "Valuation already prices in best-case deal wins.",
    "summary": "Contrarian view: upside is largely priced in already.",
    "error": None,
}

_FIXTURE_VALUATION: dict[str, Any] = {
    "agent_name": "valuation_agent",
    "intrinsic_value_per_share": 4100.0,
    "current_price": 3850.0,
    "upside_downside_pct": 6.5,
    "valuation_verdict": "undervalued",
    "dcf_wacc_pct": 11.5,
    "dcf_terminal_growth_pct": 4.0,
    "dcf_projection_years": 10,
    "dcf_sector_used": "IT Services",
    "pe_ratio": 28.5,
    "sector_avg_pe": 26.0,
    "pb_ratio": 12.0,
    "sector_avg_pb": 10.5,
    "ev_ebitda": 19.0,
    "sector_avg_ev_ebitda": 18.0,
    "peer_tickers": ["INFY.NS", "WIPRO.NS"],
    "premium_discount_to_peers_pct": 5.0,
    "margin_of_safety": "moderate",
    "summary": "DCF suggests modest undervaluation versus current price.",
    "error": None,
}

_FIXTURE_DEBATE_ROUNDS: list[dict[str, Any]] = [
    {
        "round_number": 1,
        # Keyed by the same short InvestmentState field names
        # backend.graph.nodes._build_agent_responses actually uses
        # ("fundamental", "technical", "sentiment", "macro", "risk") --
        # NOT the full agent_name enum values. Only the four research
        # agents plus Risk Officer participate in agent_responses; the
        # Contrarian's own text lives in the round's separate
        # "contrarian" key, and Valuation/Portfolio Manager run outside
        # the debate loop entirely.
        "agent_responses": {
            "fundamental": "Growth remains durable given deal pipeline.",
            "risk": "Concentration risk is manageable at current levels.",
        },
        "contrarian": "Deal pipeline strength is already priced into the stock.",
        "completed_at": "2026-08-01T10:00:00Z",
    },
    {
        "round_number": 2,
        "agent_responses": {
            "technical": "Even after the contrarian challenge, momentum holds up.",
        },
        "contrarian": "Upside assumes no margin compression -- a real risk.",
        "completed_at": "2026-08-01T10:05:00Z",
    },
]

_FIXTURE_DECISION: dict[str, Any] = {
    "agent_name": "portfolio_manager",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "verdict": "BUY",
    "conviction_score": 8,
    "price_target": "Rs 4,200 (12-month)",
    "time_horizon": "12 months",
    "executive_summary": "TCS presents a durable growth story at a fair valuation.",
    "investment_thesis": (
        "Deal wins, margin resilience, and stable macro support a BUY."
    ),
    "bull_case": "Strong FCF generation and consistent deal pipeline.",
    "bear_case": "BFSI concentration and margin pressure from wage inflation.",
    "risk_summary": "Low overall risk; concentration is the key watch item.",
    "valuation_summary": "DCF and peer multiples both suggest modest undervaluation.",
    "key_risks": ["BFSI concentration", "Wage inflation"],
    "key_catalysts": ["Large deal ramp-ups", "AI services adoption"],
    "contrarian_response": (
        "Upside is real but partially priced in -- BUY, not STRONG BUY."
    ),
    "debate_rounds_used": 2,
    "agent_weights": {"fundamental_analyst": 0.3, "valuation_agent": 0.25},
    "summary": "BUY with conviction 8/10 and a 12-month price target of Rs 4,200.",
    "generated_at": "2026-08-01 10:06:00.000000",
    "error": None,
}

_FIXTURE_STATE_SNAPSHOT: dict[str, Any] = {
    "job_id": "fixture-job-id",
    "company_name": "Tata Consultancy Services",
    "ticker": "TCS.NS",
    "status": "completed",
    "fundamental": _FIXTURE_FUNDAMENTAL,
    "technical": _FIXTURE_TECHNICAL,
    "sentiment": _FIXTURE_SENTIMENT,
    "macro": _FIXTURE_MACRO,
    "debate_rounds": _FIXTURE_DEBATE_ROUNDS,
    "risk": _FIXTURE_RISK,
    "contrarian": _FIXTURE_CONTRARIAN,
    "valuation": _FIXTURE_VALUATION,
    "decision": _FIXTURE_DECISION,
}


# ---------------------------------------------------------------------------
# build_memo_context() -- not found / ownership
# ---------------------------------------------------------------------------


class TestBuildMemoContextNotFound:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_row_exists(self) -> None:
        session = _make_session_returning_row(None)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_a_different_users_analysis(self) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        row = _make_row(user_id=owner_id, state_snapshot=_FIXTURE_STATE_SNAPSHOT)
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=requester_id
        )

        assert result is None


# ---------------------------------------------------------------------------
# build_memo_context() -- not ready
# ---------------------------------------------------------------------------


class TestBuildMemoContextNotReady:
    @pytest.mark.asyncio
    async def test_pending_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="pending")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "pending"

    @pytest.mark.asyncio
    async def test_running_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="running")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "running"

    @pytest.mark.asyncio
    async def test_failed_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="failed")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "failed"

    @pytest.mark.asyncio
    async def test_completed_with_null_snapshot_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="completed", state_snapshot=None)
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)

    @pytest.mark.asyncio
    async def test_completed_with_no_decision_key_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"job_id": "abc", "status": "completed"},
        )
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)

    @pytest.mark.asyncio
    async def test_malformed_json_string_snapshot_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot="{not valid json"
        )
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await build_memo_context(session, analysis_id=uuid.uuid4(), user_id=user_id)


# ---------------------------------------------------------------------------
# build_memo_context() -- success, against the shared fixture analysis
# ---------------------------------------------------------------------------


class TestBuildMemoContextSuccess:
    @pytest.mark.asyncio
    async def test_returns_memo_chat_context(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=analysis_id, user_id=user_id
        )

        assert isinstance(result, MemoChatContext)
        assert result.analysis_id == analysis_id

    @pytest.mark.asyncio
    async def test_company_name_and_ticker_from_decision(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.company_name == "Tata Consultancy Services"
        assert result.ticker == "TCS.NS"

    @pytest.mark.asyncio
    async def test_psycopg2_style_string_snapshot_is_parsed(self) -> None:
        """asyncpg returns JSONB as a dict already; psycopg2 returns a
        JSON string -- both must produce an identical result."""
        import json

        user_id = uuid.uuid4()
        snapshot_json = json.dumps(_FIXTURE_STATE_SNAPSHOT)
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=snapshot_json
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.company_name == "Tata Consultancy Services"

    @pytest.mark.asyncio
    async def test_queries_with_correct_analysis_id_parameter(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        await build_memo_context(session, analysis_id=analysis_id, user_id=user_id)

        session.execute.assert_awaited_once()
        bound_params = session.execute.call_args.args[1]
        assert bound_params == {"analysis_id": str(analysis_id)}

    @pytest.mark.asyncio
    async def test_all_seven_agent_sections_are_populated(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert "TCS shows strong fundamentals" in result.fundamental_section
        assert "Technical picture is bullish" in result.technical_section
        assert "News sentiment is broadly positive" in result.sentiment_section
        assert "Macro backdrop is supportive" in result.macro_section
        assert "Overall risk is low" in result.risk_section
        assert "upside is largely priced in" in result.contrarian_section
        assert "modest undervaluation" in result.valuation_section

    @pytest.mark.asyncio
    async def test_debate_transcript_section_has_both_rounds(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert "Round 1:" in result.debate_transcript_section
        assert "Round 2:" in result.debate_transcript_section
        assert "Deal pipeline strength is already priced in" in (
            result.debate_transcript_section
        )

    @pytest.mark.asyncio
    async def test_decision_section_has_verdict_and_thesis(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert "BUY" in result.decision_section
        assert "durable growth story" in result.decision_section

    @pytest.mark.asyncio
    async def test_full_context_joins_every_section_with_headings(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id, status="completed", state_snapshot=_FIXTURE_STATE_SNAPSHOT
        )
        session = _make_session_returning_row(row)

        result = await build_memo_context(
            session, analysis_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        full = result.full_context
        for display_name in AGENT_DISPLAY_NAMES.values():
            assert f"## {display_name}" in full
        assert "## Debate Transcript" in full
        assert "## Portfolio Manager Decision" in full
        assert "Tata Consultancy Services" in full
        assert "TCS.NS" in full


# ---------------------------------------------------------------------------
# AGENT_STATE_KEYS / AGENT_DISPLAY_NAMES -- shape sanity
# ---------------------------------------------------------------------------


class TestAgentConstants:
    def test_seven_agent_keys(self) -> None:
        assert len(AGENT_STATE_KEYS) == 7

    def test_every_key_has_a_display_name(self) -> None:
        for key in AGENT_STATE_KEYS:
            assert key in AGENT_DISPLAY_NAMES

    def test_no_portfolio_manager_key(self) -> None:
        # the Portfolio Manager's own output is "decision", not one of
        # the 7 agent output keys -- see the acceptance criteria's own
        # wording: "all 7 agent outputs + debate transcript + decision"
        assert "decision" not in AGENT_STATE_KEYS
        assert "portfolio_manager" not in AGENT_STATE_KEYS


# ---------------------------------------------------------------------------
# Per-agent section formatters -- missing / error / populated
# ---------------------------------------------------------------------------


class TestFundamentalSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_fundamental_section(None)

    def test_empty_dict_input(self) -> None:
        assert "no output available" in _format_fundamental_section({})

    def test_agent_error(self) -> None:
        text = _format_fundamental_section({"error": "yFinance timeout"})
        assert "agent reported an error" in text
        assert "yFinance timeout" in text

    def test_populated_output(self) -> None:
        text = _format_fundamental_section(_FIXTURE_FUNDAMENTAL)
        assert "8/10" in text
        assert "12.50%" in text
        assert "Consistent revenue growth" in text
        assert "TCS shows strong fundamentals" in text


class TestTechnicalSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_technical_section(None)

    def test_agent_error(self) -> None:
        text = _format_technical_section({"error": "OHLCV fetch failed"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_technical_section(_FIXTURE_TECHNICAL)
        assert "BUY" in text
        assert "golden cross: yes" in text
        assert "Technical picture is bullish" in text


class TestSentimentSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_sentiment_section(None)

    def test_agent_error(self) -> None:
        text = _format_sentiment_section({"error": "NewsAPI quota exceeded"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_sentiment_section(_FIXTURE_SENTIMENT)
        assert "positive" in text
        assert "TCS wins large deal with European bank" in text


class TestMacroSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_macro_section(None)

    def test_agent_error(self) -> None:
        text = _format_macro_section({"error": "RBI scraper down"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_macro_section(_FIXTURE_MACRO)
        assert "stable" in text
        assert "Resilient domestic demand" in text


class TestRiskSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_risk_section(None)

    def test_agent_error(self) -> None:
        text = _format_risk_section({"error": "upstream agent failed"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_risk_section(_FIXTURE_RISK)
        assert "3/10" in text
        assert "High revenue concentration in BFSI vertical" in text


class TestContrarianSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_contrarian_section(None)

    def test_agent_error(self) -> None:
        text = _format_contrarian_section({"error": "debate state incomplete"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_contrarian_section(_FIXTURE_CONTRARIAN)
        assert "Valuation already prices in best-case deal wins." in text


class TestValuationSectionFormatter:
    def test_none_input(self) -> None:
        assert "no output available" in _format_valuation_section(None)

    def test_agent_error(self) -> None:
        text = _format_valuation_section({"error": "Screener.in scrape failed"})
        assert "agent reported an error" in text

    def test_populated_output(self) -> None:
        text = _format_valuation_section(_FIXTURE_VALUATION)
        assert "undervalued" in text
        assert "INFY.NS" in text
        assert "WIPRO.NS" in text


# ---------------------------------------------------------------------------
# Debate transcript formatter
# ---------------------------------------------------------------------------


class TestDebateTranscriptFormatter:
    def test_none_input(self) -> None:
        assert "No debate rounds" in _format_debate_transcript_section(None)

    def test_empty_list_input(self) -> None:
        assert "No debate rounds" in _format_debate_transcript_section([])

    def test_non_dict_entries_are_skipped(self) -> None:
        rounds: list[Any] = ["not a dict", _FIXTURE_DEBATE_ROUNDS[0]]
        text = _format_debate_transcript_section(rounds)
        assert "Round 1:" in text

    def test_round_with_no_agent_responses(self) -> None:
        rounds = [{"round_number": 1, "agent_responses": {}, "contrarian": None}]
        text = _format_debate_transcript_section(rounds)
        assert "no agent responses recorded" in text

    def test_populated_transcript_uses_display_names(self) -> None:
        text = _format_debate_transcript_section(_FIXTURE_DEBATE_ROUNDS)
        assert AGENT_DISPLAY_NAMES["fundamental"] in text  # "Fundamental Analyst"
        assert AGENT_DISPLAY_NAMES["risk"] in text  # "Risk Officer"
        assert "Contrarian challenge:" in text


# ---------------------------------------------------------------------------
# Decision formatter
# ---------------------------------------------------------------------------


class TestDecisionSectionFormatter:
    def test_none_input(self) -> None:
        assert "not available" in _format_decision_section(None)

    def test_empty_dict_input(self) -> None:
        assert "not available" in _format_decision_section({})

    def test_agent_error(self) -> None:
        text = _format_decision_section({"error": "synthesis failed"})
        assert "agent reported an error" in text

    def test_populated_decision(self) -> None:
        text = _format_decision_section(_FIXTURE_DECISION)
        assert "BUY" in text
        assert "conviction 8/10" in text
        assert "Rs 4,200 (12-month)" in text
        assert "fundamental_analyst: 0.30" in text

    def test_missing_agent_weights_falls_back(self) -> None:
        decision = dict(_FIXTURE_DECISION)
        decision.pop("agent_weights")
        text = _format_decision_section(decision)
        assert "not provided" in text
