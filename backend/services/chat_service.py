# backend/services/chat_service.py
"""
AIRP -- AIRP Assistant Memo-Scoped Context Builder (T-100)

Builds the grounded text context a memo-scoped chat session (T-099's
``chat_sessions.session_type = 'memo_scoped'``) needs to answer questions
about one completed analysis: all 7 research/advanced agent outputs, the
full debate transcript, and the Portfolio Manager's final decision --
assembled directly from ``analyses.state_snapshot``, with no vector
search, no embeddings, and no ChromaDB involved.

Why no vector search for this scope?
One analysis's full state (7 agent outputs + debate transcript +
decision) is small enough -- a few thousand tokens at most -- to hand an
LLM in full, every time, as-is. Retrieval-augmented generation exists to
select a relevant subset out of a corpus too large to fit in context;
there is no such corpus here, only one already-bounded record the user
explicitly opened a chat about. Running it through embeddings and
similarity search would add latency, cost, and a whole new failure mode
(a relevant fact getting a low similarity score and never being
retrieved) for zero benefit over just reading the record. Portfolio-wide
questions ("which of my BUY calls are up this month?", "search my
uploaded annual reports for a mention of X") are a genuinely different
problem -- unbounded scope across many analyses/documents -- and that is
exactly what T-101's LangChain tool-calling layer (``get_user_analyses``,
``get_memo_by_ticker``, ``search_uploaded_documents`` over the existing
``airp_documents`` ChromaDB collection) is for.

Why read ``analyses.state_snapshot`` directly, not the ``agent_outputs``
table?
Both exist. ``agent_outputs`` (T-016) stores one row per agent per
analysis primarily for observability -- token counts, latency,
LangSmith run IDs -- alongside its ``output_json`` payload.
``state_snapshot`` (T-033) stores the same agent output content plus the
debate transcript and the final decision *together*, as the exact
InvestmentState the LangGraph pipeline actually produced, in one column,
already reachable with the same one-row-per-job_id query that
``backend.services.analysis.get_analysis_result`` uses for the results
page. This module reuses that exact pattern for the same reason that
module documents for itself: ``state_snapshot`` is a T-033-migration-only
column, never added to the ``Analysis`` ORM model, so it is read via raw
SQL (``sqlalchemy.text``), not the ORM.

Why does this module define no chat-turn / LLM-calling logic?
T-100 is scoped to context assembly only, per its own acceptance
criteria ("context builder returns ... as structured text"). The actual
chat loop -- taking a user question, this context, and an LLM call, and
producing an answer -- is a separate, later task; keeping this module a
pure "analysis_id in, structured text out" function keeps it trivially
unit-testable without mocking any LLM client, and reusable unchanged
once that chat loop is built.

Ownership and readiness semantics
----------------------------------
``build_memo_context`` mirrors ``get_analysis_result``'s contract
exactly (same not-found/ownership/readiness rules, same
``AnalysisNotReadyError`` type, imported rather than redefined so the
whole app shares one error taxonomy for "this analysis is not ready
yet"):

    * No ``analyses`` row for ``analysis_id``            -> None
    * Row exists but belongs to a different user          -> None
      (never distinguishes this from "row does not exist" -- identical
      to every other read path in this codebase that takes a user_id)
    * Row exists, is the caller's, but ``status`` is not
      'completed'                                         -> raises
      ``AnalysisNotReadyError(status=...)``
    * Row exists, is the caller's, ``status='completed'``,
      but the snapshot is missing or has no ``decision`` key
      (should not happen given ``portfolio_manager_node``'s contract,
      but treated defensively, exactly as ``get_analysis_result`` does)
                                                            -> raises
      ``AnalysisNotReadyError(status=status)``
    * Otherwise                                            -> returns a
      populated ``MemoChatContext``

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- this module lives beside
  ``backend/services/analysis.py`` and ``backend/services/auth.py``,
  neither of which uses it, for the same reason: it breaks Pydantic v2
  union resolution for modules that import this one, and this module's
  own callers (a future chat router/service) will.
* Plain ASCII section comments (# ---) -- established AIRP convention
  from T-024 onward.
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* Every per-agent formatter degrades independently and never raises: a
  missing agent output, an agent that returned ``error`` set, or a
  malformed field all produce a clearly-labelled fallback line rather
  than an exception -- the same "agents/nodes never raise" contract
  ``backend/services/memo_generator.py`` already applies to memo
  rendering, extended here to context rendering for the chatbot.
* Per-agent formatters are private (``_format_*``) but directly unit
  tested, matching the precedent set by ``backend/db/session.py``'s
  ``_prepare_url``/``_build_database_url`` (tested directly in
  ``test_orm_models.py``) -- pure functions with no I/O are tested
  directly for fine-grained coverage, not only indirectly through the
  public entry point.

Public API
----------
    from backend.services.chat_service import (
        MemoChatContext,
        build_memo_context,
    )
"""

from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Optional
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.analysis import AnalysisNotReadyError

logger = logging.getLogger(__name__)

__all__ = [
    "MemoChatContext",
    "build_memo_context",
    "AGENT_STATE_KEYS",
    "AGENT_DISPLAY_NAMES",
]

# ---------------------------------------------------------------------------
# Constants -- the 7 agent outputs this context covers (research +
# advanced agents; the Portfolio Manager's own output is handled
# separately as "decision", per the acceptance criteria's own wording:
# "all 7 agent outputs + debate transcript + decision").
# ---------------------------------------------------------------------------

#: InvestmentState keys for the 7 non-Portfolio-Manager agent outputs,
#: in the same pipeline order backend/graph/state.py documents them
#: (4 parallel research agents, then the 3 post-debate advanced agents).
AGENT_STATE_KEYS: tuple[str, ...] = (
    "fundamental",
    "technical",
    "sentiment",
    "macro",
    "risk",
    "contrarian",
    "valuation",
)

#: Human-readable display name for each agent, keyed the same way.
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "fundamental": "Fundamental Analyst",
    "technical": "Technical Analyst",
    "sentiment": "News Sentiment Agent",
    "macro": "Macro Economist",
    "risk": "Risk Officer",
    "contrarian": "Contrarian Investor",
    "valuation": "Valuation Agent",
}

_NOT_AVAILABLE = "not available"
_NOT_PROVIDED = "not provided"
_NONE_NOTED = "none noted"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoChatContext:
    """
    Grounded, structured context for one memo-scoped chat session.

    Every field beyond the identity fields is a self-contained block of
    plain text for one part of the analysis -- the 7 agent sections,
    the debate transcript, and the final decision -- so a caller can
    quote or reference a single section, or read ``full_context`` for
    everything joined together with headings, ready to drop straight
    into an LLM prompt.
    """

    analysis_id: uuid.UUID
    company_name: str
    ticker: str
    fundamental_section: str
    technical_section: str
    sentiment_section: str
    macro_section: str
    risk_section: str
    contrarian_section: str
    valuation_section: str
    debate_transcript_section: str
    decision_section: str

    @property
    def full_context(self) -> str:
        """
        All sections joined into one prompt-ready block, in pipeline
        order (4 parallel research agents, debate transcript, 3
        post-debate advanced agents, final decision) with a heading in
        front of each section and the analysis identity at the top.
        """
        parts = [
            f"Analysis of {self.company_name} ({self.ticker}), "
            f"analysis_id={self.analysis_id}.",
            f"## {AGENT_DISPLAY_NAMES['fundamental']}\n{self.fundamental_section}",
            f"## {AGENT_DISPLAY_NAMES['technical']}\n{self.technical_section}",
            f"## {AGENT_DISPLAY_NAMES['sentiment']}\n{self.sentiment_section}",
            f"## {AGENT_DISPLAY_NAMES['macro']}\n{self.macro_section}",
            f"## Debate Transcript\n{self.debate_transcript_section}",
            f"## {AGENT_DISPLAY_NAMES['risk']}\n{self.risk_section}",
            f"## {AGENT_DISPLAY_NAMES['contrarian']}\n{self.contrarian_section}",
            f"## {AGENT_DISPLAY_NAMES['valuation']}\n{self.valuation_section}",
            f"## Portfolio Manager Decision\n{self.decision_section}",
        ]
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Formatting helpers -- pure, never raise
# ---------------------------------------------------------------------------


def _fmt_num(value: Any, unit: str = "", fallback: str = _NOT_AVAILABLE) -> str:
    """Render a numeric field: floats to 2dp, ints/other as-is, None as fallback."""
    if value is None:
        return fallback
    if isinstance(value, bool):
        # bool is a subclass of int in Python -- must be checked before
        # the float/int branches below or True/False would render as "1"/"0".
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}{unit}"
    if isinstance(value, int):
        return f"{value}{unit}"
    return f"{value}{unit}"


def _fmt_bool(value: Any, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    return "yes" if value else "no"


def _fmt_list(value: Any, empty: str = _NONE_NOTED) -> str:
    if not value or not isinstance(value, list):
        return empty
    return "; ".join(str(item) for item in value)


def _fmt_text(value: Any, fallback: str = _NOT_AVAILABLE) -> str:
    if not value or not isinstance(value, str):
        return fallback
    return value


# ---------------------------------------------------------------------------
# Per-agent section formatters -- one per AGENT_STATE_KEYS entry
# ---------------------------------------------------------------------------


def _format_fundamental_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Fundamental Analyst: no output available for this analysis."
    if data.get("error"):
        return f"Fundamental Analyst: agent reported an error -- {data['error']}"
    lines = [
        f"Score: {_fmt_num(data.get('score'))}/10 "
        f"(data quality: {data.get('data_quality', 'unknown')}, "
        f"based on {_fmt_num(data.get('years_available'))} of 4 years available)",
        f"Revenue growth: {_fmt_num(data.get('revenue_growth_pct'), '%')} YoY, "
        f"{_fmt_num(data.get('revenue_cagr_3y_pct'), '%')} 3-year CAGR",
        f"Margins: gross {_fmt_num(data.get('gross_margin_pct'), '%')}, "
        f"operating {_fmt_num(data.get('operating_margin_pct'), '%')}, "
        f"net {_fmt_num(data.get('net_margin_pct'), '%')}",
        f"Free cash flow: Rs {_fmt_num(data.get('free_cash_flow_cr'))} crore "
        f"(FCF yield {_fmt_num(data.get('fcf_yield_pct'), '%')})",
        f"Balance sheet: debt/equity {_fmt_num(data.get('debt_to_equity'))}, "
        f"current ratio {_fmt_num(data.get('current_ratio'))}, "
        f"interest coverage {_fmt_num(data.get('interest_coverage'))}",
        f"Returns: ROE {_fmt_num(data.get('roe_pct'), '%')}, "
        f"ROCE {_fmt_num(data.get('roce_pct'), '%')}",
        f"Strengths: {_fmt_list(data.get('strengths'))}",
        f"Weaknesses: {_fmt_list(data.get('weaknesses'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_technical_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Technical Analyst: no output available for this analysis."
    if data.get("error"):
        return f"Technical Analyst: agent reported an error -- {data['error']}"
    lines = [
        f"Signal: {data.get('signal', 'unknown')} "
        f"(strength {_fmt_num(data.get('signal_strength'))}/10)",
        f"Current price: {_fmt_num(data.get('current_price'))}, "
        f"52-week range {_fmt_num(data.get('week_52_low'))}-"
        f"{_fmt_num(data.get('week_52_high'))} "
        f"({_fmt_num(data.get('price_vs_52w_high_pct'), '%')} vs. 52w high)",
        f"Moving averages: 50d {_fmt_num(data.get('ma_50d'))}, "
        f"200d {_fmt_num(data.get('ma_200d'))} "
        f"(above 50d: {_fmt_bool(data.get('price_above_ma50'))}, "
        f"above 200d: {_fmt_bool(data.get('price_above_ma200'))}, "
        f"golden cross: {_fmt_bool(data.get('golden_cross'))})",
        f"RSI (14d): {_fmt_num(data.get('rsi_14'))}",
        f"Momentum: 1m {_fmt_num(data.get('momentum_1m_pct'), '%')}, "
        f"3m {_fmt_num(data.get('momentum_3m_pct'), '%')}, "
        f"6m {_fmt_num(data.get('momentum_6m_pct'), '%')}, "
        f"1y {_fmt_num(data.get('momentum_1y_pct'), '%')}",
        f"Volume trend: {data.get('volume_trend') or 'unknown'}",
        f"Support levels: {_fmt_list(data.get('support_levels'))}",
        f"Resistance levels: {_fmt_list(data.get('resistance_levels'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_sentiment_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "News Sentiment Agent: no output available for this analysis."
    if data.get("error"):
        return f"News Sentiment Agent: agent reported an error -- {data['error']}"
    lines = [
        f"Sentiment: {data.get('sentiment_label', 'unknown')} "
        f"(score {_fmt_num(data.get('sentiment_score'))})",
        f"Articles analysed: {_fmt_num(data.get('articles_analysed'))} total "
        f"({_fmt_num(data.get('positive_articles'))} positive, "
        f"{_fmt_num(data.get('negative_articles'))} negative, "
        f"{_fmt_num(data.get('neutral_articles'))} neutral)",
        f"Red flags ({_fmt_num(data.get('red_flag_count'))}): "
        f"{_fmt_list(data.get('red_flags'))}",
        f"Top positive headlines: {_fmt_list(data.get('top_positive_headlines'))}",
        f"Top negative headlines: {_fmt_list(data.get('top_negative_headlines'))}",
        f"Dominant topics: {_fmt_list(data.get('dominant_topics'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_macro_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Macro Economist: no output available for this analysis."
    if data.get("error"):
        return f"Macro Economist: agent reported an error -- {data['error']}"
    lines = [
        f"Macro environment: {data.get('macro_environment', 'unknown')}",
        f"Sector impact: {data.get('sector_impact', 'unknown')}",
        f"RBI repo rate: {_fmt_num(data.get('rbi_repo_rate_pct'), '%')} "
        f"(stance: {data.get('rate_stance') or 'unknown'}, "
        f"direction: {data.get('rate_direction') or 'unknown'})",
        f"Inflation: CPI {_fmt_num(data.get('cpi_inflation_pct'), '%')}, "
        f"WPI {_fmt_num(data.get('wpi_inflation_pct'), '%')} "
        f"(trend: {data.get('inflation_trend') or 'unknown'})",
        f"GDP growth: {_fmt_num(data.get('gdp_growth_pct'), '%')} "
        f"(forecast {_fmt_num(data.get('gdp_forecast_pct'), '%')})",
        f"USD/INR: {_fmt_num(data.get('usd_inr_rate'))} "
        f"(trend: {data.get('inr_trend') or 'unknown'})",
        f"Tailwinds: {_fmt_list(data.get('tailwinds'))}",
        f"Headwinds: {_fmt_list(data.get('headwinds'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_risk_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Risk Officer: no output available for this analysis."
    if data.get("error"):
        return f"Risk Officer: agent reported an error -- {data['error']}"
    lines = [
        f"Overall risk score: {_fmt_num(data.get('risk_score'))}/10",
        f"Breakdown: governance {_fmt_num(data.get('governance_risk'))}/10, "
        f"regulatory {_fmt_num(data.get('regulatory_risk'))}/10, "
        f"financial {_fmt_num(data.get('financial_risk'))}/10, "
        f"concentration {_fmt_num(data.get('concentration_risk'))}/10",
        f"Risk flags: {_fmt_list(data.get('risk_flags'))}",
        f"Critical flags: {_fmt_list(data.get('critical_flags'))}",
        f"Recommendation: {_fmt_text(data.get('risk_recommendation'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_contrarian_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Contrarian Investor: no output available for this analysis."
    if data.get("error"):
        return f"Contrarian Investor: agent reported an error -- {data['error']}"
    lines = [
        f"Bear conviction: {_fmt_num(data.get('bear_conviction'))}/10",
        f"Strongest argument: {_fmt_text(data.get('strongest_argument'))}",
        f"Counter-arguments: {_fmt_list(data.get('counter_arguments'))}",
        f"Agents challenged: {_fmt_list(data.get('challenged_agents'))}",
        f"Overlooked risks: {_fmt_list(data.get('overlooked_risks'))}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


def _format_valuation_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Valuation Agent: no output available for this analysis."
    if data.get("error"):
        return f"Valuation Agent: agent reported an error -- {data['error']}"
    lines = [
        f"Verdict: {data.get('valuation_verdict', 'unknown')}",
        f"Intrinsic value/share: {_fmt_num(data.get('intrinsic_value_per_share'))} "
        f"vs. current price {_fmt_num(data.get('current_price'))} "
        f"({_fmt_num(data.get('upside_downside_pct'), '%')} upside/downside)",
        f"DCF assumptions: WACC {_fmt_num(data.get('dcf_wacc_pct'), '%')}, "
        f"terminal growth {_fmt_num(data.get('dcf_terminal_growth_pct'), '%')}, "
        f"{_fmt_num(data.get('dcf_projection_years'))}-year projection "
        f"(sector table: {data.get('dcf_sector_used') or 'default'})",
        f"Multiples: P/E {_fmt_num(data.get('pe_ratio'))} "
        f"(sector avg {_fmt_num(data.get('sector_avg_pe'))}), "
        f"P/B {_fmt_num(data.get('pb_ratio'))} "
        f"(sector avg {_fmt_num(data.get('sector_avg_pb'))}), "
        f"EV/EBITDA {_fmt_num(data.get('ev_ebitda'))} "
        f"(sector avg {_fmt_num(data.get('sector_avg_ev_ebitda'))})",
        f"Peer comparison: {_fmt_list(data.get('peer_tickers'))} "
        f"({_fmt_num(data.get('premium_discount_to_peers_pct'), '%')} "
        f"premium/discount to peers)",
        f"Margin of safety: {data.get('margin_of_safety') or 'not provided'}",
        f"Summary: {_fmt_text(data.get('summary'))}",
    ]
    return "\n".join(lines)


_SectionFormatter = Callable[[Optional[dict[str, Any]]], str]

_SECTION_FORMATTERS: dict[str, _SectionFormatter] = {
    "fundamental": _format_fundamental_section,
    "technical": _format_technical_section,
    "sentiment": _format_sentiment_section,
    "macro": _format_macro_section,
    "risk": _format_risk_section,
    "contrarian": _format_contrarian_section,
    "valuation": _format_valuation_section,
}


def _format_debate_transcript_section(rounds: Optional[list[Any]]) -> str:
    """
    Render ``InvestmentState["debate_rounds"]`` (see
    ``backend.graph.state.DebateRound``'s documented dict shape:
    ``round_number``, ``agent_responses``, ``contrarian``,
    ``completed_at``) as one block of text, one round per paragraph.
    """
    if not rounds or not isinstance(rounds, list):
        return "No debate rounds were recorded for this analysis."

    blocks: list[str] = []
    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        round_number = round_data.get("round_number", "?")
        lines = [f"Round {round_number}:"]

        responses = round_data.get("agent_responses")
        if isinstance(responses, dict) and responses:
            for agent_name, response_text in responses.items():
                display_name = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
                lines.append(f"  {display_name}: {response_text}")
        else:
            lines.append("  (no agent responses recorded for this round)")

        contrarian_text = round_data.get("contrarian")
        if contrarian_text:
            lines.append(f"  Contrarian challenge: {contrarian_text}")

        blocks.append("\n".join(lines))

    if not blocks:
        return "No debate rounds were recorded for this analysis."
    return "\n\n".join(blocks)


def _format_decision_section(data: Optional[dict[str, Any]]) -> str:
    if not isinstance(data, dict) or not data:
        return "Portfolio Manager decision: not available."
    if data.get("error"):
        return f"Portfolio Manager: agent reported an error -- {data['error']}"

    weights = data.get("agent_weights")
    if isinstance(weights, dict) and weights:
        weights_text = ", ".join(
            f"{name}: {_fmt_num(weight)}" for name, weight in weights.items()
        )
    else:
        weights_text = _NOT_PROVIDED

    lines = [
        f"Verdict: {data.get('verdict', 'unknown')} "
        f"(conviction {_fmt_num(data.get('conviction_score'))}/10, "
        f"time horizon: {data.get('time_horizon') or 'not specified'})",
        f"Price target: {data.get('price_target') or _NOT_PROVIDED}",
        f"Executive summary: {_fmt_text(data.get('executive_summary'))}",
        f"Investment thesis: {_fmt_text(data.get('investment_thesis'))}",
        f"Bull case: {_fmt_text(data.get('bull_case'))}",
        f"Bear case: {_fmt_text(data.get('bear_case'))}",
        f"Risk summary: {_fmt_text(data.get('risk_summary'))}",
        f"Valuation summary: {_fmt_text(data.get('valuation_summary'))}",
        f"Key risks: {_fmt_list(data.get('key_risks'))}",
        f"Key catalysts: {_fmt_list(data.get('key_catalysts'))}",
        f"Contrarian response: {_fmt_text(data.get('contrarian_response'))}",
        f"Debate rounds used: {_fmt_num(data.get('debate_rounds_used'))}",
        f"Agent weights: {weights_text}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshot loading -- mirrors backend.services.analysis's own raw-SQL
# pattern for the exact same reason (state_snapshot is a T-033-migration
# column, never added to the Analysis ORM model).
# ---------------------------------------------------------------------------

#: Reads the three columns build_memo_context needs in one round trip:
#: ownership (user_id), lifecycle status (to distinguish "not ready"
#: from "ready"), and the full state snapshot every section is read
#: from. Deliberately the same query shape as
#: backend.services.analysis._SQL_LOAD_RESULT.
_SQL_LOAD_STATE_SNAPSHOT = text(
    """
    SELECT user_id,
           status,
           state_snapshot
      FROM analyses
     WHERE id = CAST(:analysis_id AS uuid)
     LIMIT 1
    """
)


def _parse_state_snapshot(
    snapshot_val: Any,
    analysis_id: uuid.UUID,
) -> Optional[dict[str, Any]]:
    """
    Normalise ``analyses.state_snapshot`` (JSONB) into a plain dict, or
    None if it is missing or malformed.

    Duplicated from ``backend.services.analysis``'s own
    ``_parse_state_snapshot`` rather than imported, for the same reason
    that module's docstring gives for not importing
    ``state_persistence``'s version: each caller only ever needs a
    handful of top-level keys back out of the same parsed dict, so one
    shared normalisation step is duplicated across each caller's own
    module rather than centralised behind a shared private helper.
    """
    if snapshot_val is None:
        return None

    if isinstance(snapshot_val, dict):
        snapshot: Any = snapshot_val
    else:
        try:
            snapshot = json.loads(str(snapshot_val))
        except json.JSONDecodeError as exc:
            logger.error(
                "_parse_state_snapshot: invalid state_snapshot JSON for "
                "analysis_id=%s: %s",
                analysis_id,
                exc,
            )
            return None

    if not isinstance(snapshot, dict):
        return None
    return snapshot


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_memo_context(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[MemoChatContext]:
    """
    Build grounded, structured chat context for one completed analysis.

    Reads ``analyses.state_snapshot`` for ``analysis_id``, verifies
    ownership, and renders the 7 agent outputs, the debate transcript,
    and the final decision into a ``MemoChatContext``. See this
    module's docstring for the full ownership/readiness contract this
    function shares with ``backend.services.analysis.get_analysis_result``.

    Args:
        session:     Active AsyncSession for this request.
        analysis_id: UUID of the analysis to build context for --
                     typically ``ChatSession.analysis_id`` for a
                     memo-scoped session.
        user_id:     UUID of the authenticated requester -- must match
                     the analysis owner or this returns None.

    Returns:
        A populated ``MemoChatContext``, or None when ``analysis_id``
        does not exist or belongs to a different user.

    Raises:
        AnalysisNotReadyError: the analysis exists and belongs to
            ``user_id``, but its status is not yet 'completed', or its
            snapshot has no usable decision.
    """
    result = await session.execute(
        _SQL_LOAD_STATE_SNAPSHOT, {"analysis_id": str(analysis_id)}
    )
    row: Any = result.fetchone()

    if row is None:
        logger.debug(
            "build_memo_context: no analyses row for analysis_id=%s",
            analysis_id,
        )
        return None

    row_user_id = row[0]
    if row_user_id is not None and uuid.UUID(str(row_user_id)) != user_id:
        logger.warning(
            "build_memo_context: analysis_id=%s belongs to a different "
            "user -- returning not-found to requester",
            analysis_id,
        )
        return None

    status = str(row[1])
    if status != "completed":
        logger.info(
            "build_memo_context: analysis_id=%s not ready (status=%s)",
            analysis_id,
            status,
        )
        raise AnalysisNotReadyError(status=status)

    snapshot = _parse_state_snapshot(row[2], analysis_id=analysis_id)
    if snapshot is None:
        logger.error(
            "build_memo_context: analysis_id=%s status=completed but "
            "state_snapshot is missing or unparseable",
            analysis_id,
        )
        raise AnalysisNotReadyError(status=status)

    decision = snapshot.get("decision")
    if not isinstance(decision, dict) or not decision:
        logger.error(
            "build_memo_context: analysis_id=%s status=completed but "
            "no decision found in state_snapshot -- treating as not ready",
            analysis_id,
        )
        raise AnalysisNotReadyError(status=status)

    company_name = str(
        decision.get("company_name") or snapshot.get("company_name") or ""
    )
    ticker = str(decision.get("ticker") or snapshot.get("ticker") or "")

    sections = {
        key: _SECTION_FORMATTERS[key](snapshot.get(key)) for key in AGENT_STATE_KEYS
    }

    return MemoChatContext(
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        fundamental_section=sections["fundamental"],
        technical_section=sections["technical"],
        sentiment_section=sections["sentiment"],
        macro_section=sections["macro"],
        risk_section=sections["risk"],
        contrarian_section=sections["contrarian"],
        valuation_section=sections["valuation"],
        debate_transcript_section=_format_debate_transcript_section(
            snapshot.get("debate_rounds")
        ),
        decision_section=_format_decision_section(decision),
    )
