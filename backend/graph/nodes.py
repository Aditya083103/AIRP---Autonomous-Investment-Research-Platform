# backend/graph/nodes.py
"""
AIRP -- LangGraph Node Functions
(T-030 / T-031 / T-032 / T-033 / T-036 / T-040 / T-041 / T-042 / T-043)

Thin wrapper functions that adapt each agent's public API to the
LangGraph node contract: receive InvestmentState, return a partial
dict that LangGraph merges back into state.

T-043 addition (Investment Memo PDF export)
-------------------------------------------
``pdf_export_node`` runs immediately after ``report_generator_node``,
the new final node before END. It reads ``state["memo_markdown"]``
(written by T-042) and renders a branded, paginated PDF via
WeasyPrint, writing it to disk and storing the resulting path in
``state["memo_pdf_path"]``. Like ``report_generator_node``, this makes
NO LLM calls -- it is a pure presentation-layer transformation. On any
failure (WeasyPrint not installed, a disabled feature flag, a
rendering or disk-write error) it degrades to
``memo_pdf_path=None`` rather than failing the pipeline -- the
Markdown memo from T-042 remains fully available regardless. See
``backend.services.pdf_export`` for the full implementation.

T-042 addition (Investment Memo generator)
-------------------------------------------
``report_generator_node`` runs immediately after ``portfolio_manager_node``,
the new final node before END. It reads ``state["decision"]`` (the
InvestmentDecision produced by T-041) and renders a structured, readable
Markdown Investment Memo into ``state["memo_markdown"]``. Like
``debate_loop_node``, this is pure data transformation with NO additional
LLM calls -- every prose section in the memo was already written by the
Portfolio Manager's own LLM synthesis step, so T-042 only formats and
assembles what already exists in state. See
``backend.services.memo_generator`` for the full implementation.

T-040 additions (multi-round debate loop)
-------------------------------------------
``debate_loop_node`` runs immediately after ``contrarian_node`` on every
debate round.  Its job is the missing piece between T-038 (Contrarian
agent that *decides* whether the consensus is wrong) and T-032's
self-loop (which only counted rounds): it builds the actual
``debate_rounds[]`` transcript entry that the acceptance criteria require.

For each completed round it:
  1. Reads the four research agents' outputs (fundamental, technical,
     sentiment, macro) plus the Risk Officer's output, all already in
     state from earlier nodes.
  2. Reads the Contrarian's current-round output (bear_conviction,
     strongest_argument, challenged_agents) -- this is the "challenge"
     every other agent is reacting to.
  3. Deterministically synthesises a short ``agent_responses`` dict:
     one sentence per agent stating whether it holds its position or
     concedes ground, based on whether the Contrarian explicitly
     challenged it and how strong the challenge is (bear_conviction).
     This is pure data transformation -- NO additional LLM calls --
     so a 2-round debate stays well under the <3 minute acceptance
     criterion (the only LLM cost per round is the Contrarian's own
     call, already paid for by contrarian_node).
  4. Appends one dict to ``state["debate_rounds"]`` matching the
     ``DebateRound`` shape documented in ``backend.graph.state``:
     ``{round_number, agent_responses, contrarian, completed_at}``.
  5. Returns the updated ``debate_rounds`` list.  Termination (max
     rounds OR no further escalation) is still decided by
     ``route_after_contrarian`` in routing.py, evaluated immediately
     after this node -- debate_loop_node never decides routing itself,
     it only records what happened in the round that just finished.

Topology change: contrarian_node -> debate_loop_node -> route_after_contrarian
(previously contrarian_node -> route_after_contrarian directly).  This is
purely additive; route_after_contrarian's decision logic is unchanged.

T-033 additions (state persistence)
-------------------------------------
Every node that runs sequentially (i.e. NOT the 4 parallel research
nodes) is wrapped by ``_persist_after(node_fn, node_name)`` which calls
``services.state_persistence.persist_state`` after the node function
returns its partial dict.

The 4 parallel research nodes (fundamental, technical, sentiment, macro)
are NOT wrapped because they run in the same Send super-step and the
persistence call would race with the research_join_node's own call.
research_join_node IS wrapped -- it runs sequentially after the join
barrier and sees the fully-merged state from all 4 research agents.

Persistence is fire-and-forget: if the DB write fails, the exception is
logged but NOT re-raised so the LangGraph pipeline continues.  This is
intentional -- a transient DB error should not abort an analysis that
is otherwise running correctly.

Architecture
------------
Every node function follows the same pattern::

    def node_name(state: InvestmentState) -> dict[str, Any]:
        ...
        return {"field": value}

LangGraph merges the returned dict into the current state automatically.

T-040 topology:
    [fundamental]  --|
    [technical]    --+--> [research_join] --> route_after_research()
    [sentiment]    --|         |                    |
    [macro]        --|    ROUTE_ERROR -> [error_handler] -> [contrarian]
                          ROUTE_ESCALATE -> [sentiment_escalation] -> [contra]
                             ROUTE_PROCEED -> [contrarian]
                                                   |
                                          [debate_loop]  (T-040: NEW)
                                                   |
                                        route_after_contrarian()
                                          |-- DEBATE_AGAIN -> [contrarian]
                                          |-- PROCEED -> [risk_officer]

T-033 persistence wrappers (sequential nodes only):
    planner_node, research_join_node, error_handler_node,
    sentiment_escalation_node, contrarian_node, debate_loop_node,
    risk_node, valuation_node, portfolio_manager_node, report_generator_node,
    pdf_export_node

T-036 performance profiling (all nodes including parallel research):
    profile_node() wraps every impl function as the INNER layer so it
    measures only the agent business logic (not DB persistence time).
    _persist_after wraps the profiled function as the OUTER layer.
    Composition order: impl -> profile_node -> _persist_after -> node
    For parallel research nodes (no persistence wrapper), composition
    is: impl -> profile_node -> node

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare type: ignore -- use cast(), explicit annotations, assert.
* _persist_after returns a synchronous wrapper because LangGraph nodes
  must be synchronous.  The async persist_state coroutine is run via
  asyncio.get_event_loop().run_until_complete() when no running loop
  exists, or scheduled as a background task when a loop is running.
  In practice, LangGraph's thread-pool executor means nodes run in a
  background thread, not the main event loop, so run_until_complete
  is the correct path.
* Persistence failures are caught and logged (non-fatal).
* In ENVIRONMENT=test, persist_state is patched to a no-op so no DB
  connections are made during unit tests.

Public API
----------
    from backend.graph.nodes import (
        planner_node, fundamental_node, technical_node,
        sentiment_node, macro_node, research_join_node,
        error_handler_node, sentiment_escalation_node,
        risk_node, contrarian_node, debate_loop_node, valuation_node,
        portfolio_manager_node,
    )
"""

import asyncio
from datetime import datetime
import logging
from typing import Any, Callable, cast

from backend.agents.contrarian_investor import run_contrarian_analysis
from backend.agents.fundamental_analyst import run_fundamental_analysis
from backend.agents.macro_economist import run_macro_analysis
from backend.agents.output_models import (
    FundamentalAnalysis,
    MacroAnalysis,
    SentimentAnalysis,
    TechnicalAnalysis,
)
from backend.agents.portfolio_manager import run_portfolio_manager_decision
from backend.agents.risk_officer import run_risk_analysis
from backend.agents.sentiment_analyst import run_sentiment_analysis
from backend.agents.technical_analyst import run_technical_analysis
from backend.agents.valuation_agent import run_valuation_analysis
from backend.graph.node_profiler import NodeTimeoutError, profile_node
from backend.graph.state import InvestmentState
from backend.services.memo_generator import generate_investment_memo
from backend.services.pdf_export import pdf_export_node as _pdf_export_node

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node name constants -- single source of truth for graph.py and tests
# ---------------------------------------------------------------------------

NODE_PLANNER = "planner"
NODE_FUNDAMENTAL = "fundamental_analyst"
NODE_TECHNICAL = "technical_analyst"
NODE_SENTIMENT = "sentiment_analyst"
NODE_MACRO = "macro_economist"
NODE_RESEARCH_JOIN = "research_join"
NODE_ERROR_HANDLER = "error_handler"
NODE_SENTIMENT_ESCALATION = "sentiment_escalation"
NODE_RISK = "risk_officer"
NODE_CONTRARIAN = "contrarian_investor"
NODE_DEBATE_LOOP = "debate_loop"
NODE_VALUATION = "valuation_agent"
NODE_PORTFOLIO_MANAGER = "portfolio_manager"
NODE_REPORT_GENERATOR = "report_generator"
NODE_PDF_EXPORT = "pdf_export"

# ---------------------------------------------------------------------------
# T-033 persistence helper
# ---------------------------------------------------------------------------

_NodeFn = Callable[[InvestmentState], dict[str, Any]]


def _state_as_plain_dict(state: InvestmentState) -> dict[str, Any]:
    """
    View an InvestmentState as a plain ``dict[str, Any]``.

    InvestmentState is a ``TypedDict`` (see backend.graph.state), which at
    runtime *is* an ordinary dict -- ``TypedDict`` exists purely for static
    type-checking and carries no runtime wrapper class. mypy, however,
    treats it as a distinct structural type, so passing an InvestmentState
    directly to a function annotated ``state: dict[str, Any]`` (e.g.
    ``generate_investment_memo``, ``pdf_export_node`` in
    ``backend.services``) fails under ``--strict`` with an ``arg-type``
    error even though the value is perfectly valid at runtime.

    ``dict(state)`` is a safe, zero-cost view (TypedDict supports the
    Mapping protocol), so the only thing needed is to tell mypy the
    resulting type explicitly via ``cast`` -- this is the AIRP-approved
    alternative to a bare ``# type: ignore``.

    Args:
        state: The InvestmentState to view as a plain dict.

    Returns:
        The same underlying mapping, typed as ``dict[str, Any]``.
    """
    return cast("dict[str, Any]", dict(state))


def _typed_dict_get(state: InvestmentState, field_name: str) -> Any:
    """
    Look up a dynamic (non-literal) key on an InvestmentState.

    ``InvestmentState.get(field_name)`` cannot be resolved to a specific
    value type by mypy when ``field_name`` is a plain ``str`` rather than
    one of the TypedDict's literal keys, so the expression's static type
    widens to ``object`` -- which then fails when passed to ``dict()``
    (no overload of ``dict`` accepts a bare ``object``). This helper
    centralises the one explicit, documented ``cast`` needed to look up a
    field by a name computed at runtime (e.g. iterating over a list of
    agent field names), instead of scattering ``# type: ignore`` comments.

    Args:
        state:      Current InvestmentState.
        field_name: The state key to read, known only at runtime.

    Returns:
        The value stored under ``field_name``, or ``None`` if absent.
        Typed as ``Any`` because the caller is expected to validate/
        narrow the result (e.g. ``isinstance(..., dict)``) before use.
    """
    return cast(Any, state.get(field_name))


def _run_persist(job_id: str, node_name: str, merged: InvestmentState) -> None:
    """
    Run persist_state synchronously, tolerating both loop contexts.

    LangGraph executes node functions in a ThreadPoolExecutor, so there
    is usually no running event loop in the calling thread.  We use
    asyncio.run() which creates a fresh event loop, runs the coroutine,
    and closes it.  This is safe from a background thread.

    Args:
        job_id:    UUID string from merged state.
        node_name: The node name that just completed.
        merged:    The merged InvestmentState to persist.
    """
    from backend.services.state_persistence import persist_state

    try:
        asyncio.run(
            persist_state(
                job_id=job_id,
                node_name=node_name,
                state=merged,
            )
        )
    except Exception as exc:
        # Persistence failures are non-fatal -- log and continue.
        logger.error(
            "_run_persist: failed to persist state after node=%s " "job_id=%s: %s",
            node_name,
            job_id,
            exc,
        )


def _persist_after(node_fn: _NodeFn, node_name: str) -> _NodeFn:
    """
    Wrap a node function to persist state after it returns (T-033).

    The wrapper:
    1. Calls the original node function to get the partial dict.
    2. Merges the partial dict with the incoming state to build the full
       state snapshot that should be persisted.
    3. Calls _run_persist (fire-and-forget, non-fatal on error).
    4. Returns the original partial dict unchanged so LangGraph can merge
       it into shared state normally.

    Only sequential nodes are wrapped -- NOT the 4 parallel research nodes.

    Args:
        node_fn:   The original node function.
        node_name: The node's string name (used in logs and DB).

    Returns:
        A wrapped function with the same signature as node_fn.
    """

    def wrapper(state: InvestmentState) -> dict[str, Any]:
        partial: dict[str, Any] = node_fn(state)

        # Build a merged view: start from incoming state, overlay the
        # partial dict that the node returned.  This is what LangGraph
        # will store as the new state, so it is what we want in the DB.
        merged_raw: dict[str, Any] = dict(state)
        merged_raw.update(partial)

        from typing import cast as typing_cast

        merged: InvestmentState = typing_cast(InvestmentState, merged_raw)

        job_id: str = str(merged.get("job_id", ""))
        if job_id:
            try:
                _run_persist(job_id=job_id, node_name=node_name, merged=merged)
            except Exception as exc:
                # Fire-and-forget: persistence errors must never abort pipeline.
                logger.error(
                    "_persist_after: _run_persist raised for node=%s " "job_id=%s: %s",
                    node_name,
                    job_id,
                    exc,
                )
        else:
            logger.warning(
                "_persist_after: no job_id in state after node=%s "
                "-- skipping persistence",
                node_name,
            )

        return partial

    return wrapper


# ---------------------------------------------------------------------------
# Planner node -- pipeline entry point (persistence-wrapped)
# ---------------------------------------------------------------------------


def _planner_node_impl(state: InvestmentState) -> dict[str, Any]:
    """Core planner logic -- validates state and sets running status."""
    ticker: str = state.get("ticker", "")
    company_name: str = state.get("company_name", "")

    if not ticker or not company_name:
        logger.error(
            "planner_node: missing required fields ticker=%r company=%r",
            ticker,
            company_name,
        )
        return {
            "status": "failed",
            "pipeline_error": (
                "Planner failed: ticker and company_name are required "
                "before the pipeline can start."
            ),
            "current_node": NODE_PLANNER,
        }

    logger.info(
        "planner_node: starting pipeline for %s (%s)",
        company_name,
        ticker,
    )
    return {
        "status": "running",
        "current_node": NODE_PLANNER,
        "started_at": datetime.utcnow().isoformat() + "Z",
    }


planner_node: _NodeFn = _persist_after(
    profile_node(_planner_node_impl, NODE_PLANNER), NODE_PLANNER
)

# ---------------------------------------------------------------------------
# Phase 2 research agent nodes -- NOT wrapped (parallel super-step)
# ---------------------------------------------------------------------------

#: Every agent function already documents "Never raises -- on failure
#: result.error is non-null" for errors *inside* its own try/except.
#: A NodeTimeoutError (or any other exception) raised by profile_node's
#: watchdog happens OUTSIDE that try/except -- at the node-wrapper layer
#: -- so it must be caught here to honour the same contract. Without
#: this, a single slow/rate-limited research agent crashes the entire
#: pipeline even though the other 3 research agents (and everything
#: downstream) would otherwise succeed. One small ``_degraded_*``
#: builder per agent below, each returning a minimal valid output model
#: with ``error`` set, mirroring exactly what each agent module already
#: builds internally on its own caught exceptions.


def _degraded_fundamental(state: InvestmentState, reason: str) -> dict[str, Any]:
    """Build a minimal, valid FundamentalAnalysis after a node failure."""
    result = FundamentalAnalysis(
        analysis_id=str(state.get("job_id", "unknown")),
        company_name=str(state.get("company_name", "Unknown Company")),
        ticker=str(state.get("ticker", "UNKNOWN")),
        score=5,
        error=reason,
    )
    return {"fundamental": result.model_dump()}


def _degraded_technical(state: InvestmentState, reason: str) -> dict[str, Any]:
    """Build a minimal, valid TechnicalAnalysis after a node failure."""
    result = TechnicalAnalysis(
        analysis_id=str(state.get("job_id", "unknown")),
        company_name=str(state.get("company_name", "Unknown Company")),
        ticker=str(state.get("ticker", "UNKNOWN")),
        signal="HOLD",
        signal_strength=1,
        error=reason,
    )
    return {"technical": result.model_dump()}


def _degraded_sentiment(state: InvestmentState, reason: str) -> dict[str, Any]:
    """Build a minimal, valid SentimentAnalysis after a node failure."""
    result = SentimentAnalysis(
        analysis_id=str(state.get("job_id", "unknown")),
        company_name=str(state.get("company_name", "Unknown Company")),
        ticker=str(state.get("ticker", "UNKNOWN")),
        sentiment_score=0.0,
        sentiment_label="neutral",
        articles_analysed=0,
        positive_articles=0,
        negative_articles=0,
        neutral_articles=0,
        error=reason,
    )
    return {"sentiment": result.model_dump()}


def _degraded_macro(state: InvestmentState, reason: str) -> dict[str, Any]:
    """Build a minimal, valid MacroAnalysis after a node failure."""
    result = MacroAnalysis(
        analysis_id=str(state.get("job_id", "unknown")),
        company_name=str(state.get("company_name", "Unknown Company")),
        ticker=str(state.get("ticker", "UNKNOWN")),
        macro_environment="neutral",
        sector_impact="neutral",
        error=reason,
    )
    return {"macro": result.model_dump()}


_DegradedFallbackFn = Callable[[InvestmentState, str], dict[str, Any]]


def _run_research_node_safely(
    state: InvestmentState,
    agent_fn: Callable[[InvestmentState], dict[str, Any]],
    node_name: str,
    degraded_fallback: _DegradedFallbackFn,
) -> dict[str, Any]:
    """
    Run one parallel research agent, never letting it crash the pipeline.

    profile_node's watchdog enforces NODE_TIMEOUT_S and re-raises
    NodeTimeoutError when an agent (most often the LLM call inside it)
    runs long -- by design, so the timeout is visible in logs and
    LangSmith. That re-raise is correct at the profiler layer, but
    without a catch *here* it propagates straight through LangGraph's
    Send super-step and aborts the whole graph.invoke() call, discarding
    every other agent's already-completed work.

    This wrapper restores the same "agents never raise" contract every
    agent module already documents for its own internal errors, but at
    the node-wrapper layer: any exception from the profiled call --
    NodeTimeoutError or otherwise (e.g. a future unhandled error from a
    new tool) -- degrades to a minimal valid output with ``error`` set,
    exactly like an in-agent failure would. Downstream nodes (risk_node,
    contrarian_node, _build_agent_responses) already check ``error`` and
    handle it gracefully, so no other code needs to change.

    Args:
        state:             Current InvestmentState.
        agent_fn:           The agent's run_*_analysis function.
        node_name:          Node name for profiling/logging.
        degraded_fallback:  Builds a minimal valid partial-state dict
                            for this agent when it fails outside its
                            own internal try/except.

    Returns:
        The agent's normal partial dict, or a degraded fallback dict
        with ``error`` set -- never raises.
    """
    try:
        return profile_node(agent_fn, node_name)(state)
    except NodeTimeoutError as exc:
        logger.error(
            "%s: timed out and was caught at the node layer -- "
            "degrading to a neutral result so the pipeline can "
            "continue with the other 3 research agents: %s",
            node_name,
            exc,
        )
        return degraded_fallback(state, f"Node timed out: {exc}")
    except Exception as exc:  # noqa: BLE001 -- last-resort safety net
        logger.exception(
            "%s: unhandled exception caught at the node layer -- "
            "degrading to a neutral result so the pipeline can "
            "continue with the other 3 research agents",
            node_name,
        )
        return degraded_fallback(state, f"Unhandled node error: {exc}")


def fundamental_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Fundamental Analyst agent.

    NOT persistence-wrapped: runs in the Send super-step alongside
    3 other research nodes.  Persistence happens in research_join_node.

    Never raises -- a timeout or unhandled error degrades to a neutral
    FundamentalAnalysis with ``error`` set (see _run_research_node_safely).

    Returns:
        Partial state dict: ``{"fundamental": <model_dump dict>}``.
    """
    logger.info(
        "fundamental_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return _run_research_node_safely(
        state, run_fundamental_analysis, NODE_FUNDAMENTAL, _degraded_fundamental
    )


def technical_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Technical Analyst agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Never raises -- a timeout or unhandled error degrades to a neutral
    TechnicalAnalysis with ``error`` set (see _run_research_node_safely).

    Returns:
        Partial state dict: ``{"technical": <model_dump dict>}``.
    """
    logger.info(
        "technical_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return _run_research_node_safely(
        state, run_technical_analysis, NODE_TECHNICAL, _degraded_technical
    )


def sentiment_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the News Sentiment Agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Never raises -- a timeout or unhandled error degrades to a neutral
    SentimentAnalysis with ``error`` set (see _run_research_node_safely).
    This is the node that triggered NodeTimeoutError in production when
    Groq's daily token quota was exhausted mid-run -- previously this
    crashed the whole pipeline; now it degrades gracefully instead.

    Returns:
        Partial state dict: ``{"sentiment": <model_dump dict>}``.
    """
    logger.info(
        "sentiment_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return _run_research_node_safely(
        state, run_sentiment_analysis, NODE_SENTIMENT, _degraded_sentiment
    )


def macro_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Macro Economist agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Never raises -- a timeout or unhandled error degrades to a neutral
    MacroAnalysis with ``error`` set (see _run_research_node_safely).

    Returns:
        Partial state dict: ``{"macro": <model_dump dict>}``.
    """
    logger.info(
        "macro_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return _run_research_node_safely(
        state, run_macro_analysis, NODE_MACRO, _degraded_macro
    )


# ---------------------------------------------------------------------------
# T-032 join node -- explicit sequential choke-point (persistence-wrapped)
# ---------------------------------------------------------------------------


def _research_join_impl(state: InvestmentState) -> dict[str, Any]:
    """
    Core research_join logic -- sets current_node after parallel join.

    Persistence here captures the fully-merged state from all 4 research
    agents, providing the richest checkpoint possible before conditional
    routing fires.
    """
    ticker: str = state.get("ticker", "unknown")
    logger.info(
        "research_join_node: all 4 research agents complete for %s -- "
        "evaluating routing conditions",
        ticker,
    )
    return {"current_node": NODE_RESEARCH_JOIN}


research_join_node: _NodeFn = _persist_after(
    profile_node(_research_join_impl, NODE_RESEARCH_JOIN), NODE_RESEARCH_JOIN
)

# ---------------------------------------------------------------------------
# T-032 routing nodes -- persistence-wrapped (run in own sequential steps)
# ---------------------------------------------------------------------------


def _error_handler_impl(state: InvestmentState) -> dict[str, Any]:
    """Core error handler logic -- writes FUNDAMENTAL_DATA_UNAVAILABLE flag."""
    fundamental_out: Any = state.get("fundamental")
    fund_error: str = "unknown fundamental data error"

    if isinstance(fundamental_out, dict):
        raw_err: Any = fundamental_out.get("error")
        if raw_err is not None:
            fund_error = str(raw_err)

    ticker: str = state.get("ticker", "unknown")
    company: str = state.get("company_name", "unknown")

    logger.error(
        "error_handler_node: fundamental data unavailable for %s (%s): %s",
        company,
        ticker,
        fund_error,
    )

    existing_risk_flags: list[str] = list(state.get("risk_flags", []))
    existing_critical_flags: list[str] = list(state.get("critical_flags", []))

    flag = "FUNDAMENTAL_DATA_UNAVAILABLE"
    if flag not in existing_risk_flags:
        existing_risk_flags.append(flag)
    if flag not in existing_critical_flags:
        existing_critical_flags.append(flag)

    pipeline_error_msg = (
        f"Fundamental data unavailable for {company} ({ticker}): {fund_error}. "
        f"Analysis continues with degraded fundamental data -- treat all "
        f"quantitative conclusions with elevated caution."
    )

    return {
        "pipeline_error": pipeline_error_msg,
        "risk_flags": existing_risk_flags,
        "critical_flags": existing_critical_flags,
        "current_node": NODE_ERROR_HANDLER,
    }


error_handler_node: _NodeFn = _persist_after(
    profile_node(_error_handler_impl, NODE_ERROR_HANDLER), NODE_ERROR_HANDLER
)


def _sentiment_escalation_impl(state: InvestmentState) -> dict[str, Any]:
    """Core sentiment escalation logic -- writes NEGATIVE_SENTIMENT flag."""
    from backend.graph.routing import (  # noqa: PLC0415
        ESCALATION_FLAG_NEGATIVE_SENTIMENT,
        NEGATIVE_SENTIMENT_THRESHOLD,
    )

    sentiment_out: Any = state.get("sentiment")
    actual_score: float = 0.0

    if isinstance(sentiment_out, dict):
        raw_score: Any = sentiment_out.get("sentiment_score")
        if isinstance(raw_score, (int, float)):
            actual_score = float(raw_score)

    ticker: str = state.get("ticker", "unknown")
    company: str = state.get("company_name", "unknown")

    logger.warning(
        "sentiment_escalation_node: sentiment_score=%.3f < %.1f for %s (%s) "
        "-- flagging for additional research",
        actual_score,
        NEGATIVE_SENTIMENT_THRESHOLD,
        company,
        ticker,
    )

    existing_risk_flags: list[str] = list(state.get("risk_flags", []))
    existing_critical_flags: list[str] = list(state.get("critical_flags", []))

    if ESCALATION_FLAG_NEGATIVE_SENTIMENT not in existing_risk_flags:
        existing_risk_flags.append(ESCALATION_FLAG_NEGATIVE_SENTIMENT)
    if ESCALATION_FLAG_NEGATIVE_SENTIMENT not in existing_critical_flags:
        existing_critical_flags.append(ESCALATION_FLAG_NEGATIVE_SENTIMENT)

    return {
        "risk_flags": existing_risk_flags,
        "critical_flags": existing_critical_flags,
        "current_node": NODE_SENTIMENT_ESCALATION,
    }


sentiment_escalation_node: _NodeFn = _persist_after(
    profile_node(_sentiment_escalation_impl, NODE_SENTIMENT_ESCALATION),
    NODE_SENTIMENT_ESCALATION,
)

# ---------------------------------------------------------------------------
# Phase 4 nodes -- T-037 Risk Officer is now fully implemented
# ---------------------------------------------------------------------------


def _risk_impl(state: InvestmentState) -> dict[str, Any]:
    """
    Delegate to the real Risk Officer agent (T-037).

    run_risk_analysis reads fundamental, technical, sentiment, and macro
    from state and returns a dict with keys: risk, risk_flags, critical_flags.
    We merge current_node into the returned dict so LangGraph tracking works.
    """
    partial: dict[str, Any] = run_risk_analysis(state)
    partial["current_node"] = NODE_RISK
    return partial


risk_node: _NodeFn = _persist_after(profile_node(_risk_impl, NODE_RISK), NODE_RISK)


def _contrarian_impl(state: InvestmentState) -> dict[str, Any]:
    """
    Delegate to the real Contrarian Investor agent (T-038).

    run_contrarian_analysis reads fundamental, technical, sentiment, macro,
    and risk from state, returning 'contrarian' and 'debate_round_count'.
    We merge current_node into the returned dict for LangGraph tracking.
    """
    partial: dict[str, Any] = run_contrarian_analysis(state)
    partial["current_node"] = NODE_CONTRARIAN
    return partial


contrarian_node: _NodeFn = _persist_after(
    profile_node(_contrarian_impl, NODE_CONTRARIAN), NODE_CONTRARIAN
)

# ---------------------------------------------------------------------------
# T-040 debate loop node -- builds the debate_rounds[] transcript entry
# ---------------------------------------------------------------------------

#: Bear conviction threshold above which an agent is described as having
#: "conceded ground" rather than merely "acknowledged" the challenge.
#: Matches the ROUTE_DEBATE_AGAIN threshold in routing.py (>= 7) so the
#: transcript language stays consistent with the routing decision that
#: follows immediately after this node.
_CONCEDE_THRESHOLD = 7


def _agent_response_text(
    agent_field_name: str,
    agent_label: str,
    agent_out: dict[str, Any],
    challenged_agents: list[str],
    bear_conviction: int,
) -> str:
    """
    Build one deterministic sentence describing how a single research
    agent "responds" to the Contrarian's current-round challenge.

    Pure function, no LLM call -- this keeps the debate loop fast enough
    to satisfy the "<3min for 2 rounds" acceptance criterion regardless
    of how many agents participate.

    Three cases:
      1. Agent output missing/errored -> neutral "no position" response.
      2. Agent was named in challenged_agents -> reacts based on
         bear_conviction (concede if >= _CONCEDE_THRESHOLD, otherwise
         push back while acknowledging the point).
      3. Agent was NOT named -> briefly reaffirms its original summary.

    Args:
        agent_field_name: InvestmentState key (e.g. "fundamental").
        agent_label:       Human-readable agent name for the sentence.
        agent_out:         The agent's own output dict (may be empty).
        challenged_agents: Contrarian's challenged_agents list this round.
        bear_conviction:   Contrarian's bear_conviction score (1-10).

    Returns:
        A single-sentence string capturing this agent's stance.
    """
    if not agent_out or agent_out.get("error"):
        return f"{agent_label} has no position this round (data unavailable)."

    own_summary: str = str(agent_out.get("summary") or "").strip()
    was_challenged: bool = agent_field_name in challenged_agents or any(
        agent_field_name in c for c in challenged_agents
    )

    if not was_challenged:
        if own_summary:
            return f"{agent_label} reaffirms its prior position: {own_summary}"
        return f"{agent_label} reaffirms its prior position; no new evidence."

    if bear_conviction >= _CONCEDE_THRESHOLD:
        return (
            f"{agent_label} concedes the Contrarian's challenge raises a "
            f"material point and acknowledges elevated uncertainty in its "
            f"original assessment."
        )
    return (
        f"{agent_label} acknowledges the Contrarian's challenge but "
        f"maintains its original assessment stands on the available evidence."
    )


def _build_agent_responses(
    state: InvestmentState,
    challenged_agents: list[str],
    bear_conviction: int,
) -> dict[str, str]:
    """
    Build the ``agent_responses`` dict for one debate round.

    One entry per agent that has run by this point in the pipeline:
    the four research agents plus the Risk Officer (when available --
    Risk Officer runs AFTER the debate loop in the T-032/T-038 topology,
    so on round 1 it is typically absent; this is handled gracefully by
    ``_agent_response_text``'s "no position" branch).

    Args:
        state:              Current InvestmentState.
        challenged_agents:  Contrarian's challenged_agents for this round.
        bear_conviction:    Contrarian's bear_conviction for this round.

    Returns:
        Dict mapping agent_name -> one-sentence response string.
    """
    agents: list[tuple[str, str]] = [
        ("fundamental", "Fundamental Analyst"),
        ("technical", "Technical Analyst"),
        ("sentiment", "News Sentiment Agent"),
        ("macro", "Macro Economist"),
        ("risk", "Risk Officer"),
    ]

    responses: dict[str, str] = {}
    for field_name, label in agents:
        agent_out: dict[str, Any] = dict(_typed_dict_get(state, field_name) or {})
        responses[field_name] = _agent_response_text(
            agent_field_name=field_name,
            agent_label=label,
            agent_out=agent_out,
            challenged_agents=challenged_agents,
            bear_conviction=bear_conviction,
        )
    return responses


def _debate_loop_impl(state: InvestmentState) -> dict[str, Any]:
    """
    Core debate_loop logic -- appends one entry to state["debate_rounds"].

    Reads the Contrarian's output that was just written by contrarian_node
    (the round that just completed) and synthesises every other agent's
    deterministic response to it, then records the whole round as a single
    dict matching the DebateRound shape documented in backend.graph.state.

    Never raises -- on missing/malformed contrarian output it still
    appends a degraded-but-valid round entry so debate_rounds[] always
    grows by exactly one entry per loop iteration (acceptance criterion:
    "debate_rounds[] contains responses from each agent").

    Args:
        state: InvestmentState immediately after contrarian_node ran.

    Returns:
        Partial state dict: {"debate_rounds": <updated list>}.
    """
    contrarian_out: dict[str, Any] = dict(state.get("contrarian") or {})

    bear_conviction_raw: Any = contrarian_out.get("bear_conviction", 1)
    bear_conviction: int = (
        int(bear_conviction_raw) if isinstance(bear_conviction_raw, int) else 1
    )

    challenged_agents: list[str] = [
        str(a) for a in (contrarian_out.get("challenged_agents") or [])
    ]

    round_number: int = int(state.get("debate_round_count") or 1)

    agent_responses: dict[str, str] = _build_agent_responses(
        state=state,
        challenged_agents=challenged_agents,
        bear_conviction=bear_conviction,
    )

    contrarian_text: str = str(
        contrarian_out.get("strongest_argument")
        or contrarian_out.get("summary")
        or "Contrarian challenge unavailable for this round."
    )

    round_entry: dict[str, Any] = {
        "round_number": round_number,
        "agent_responses": agent_responses,
        "contrarian": contrarian_text,
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }

    existing_rounds: list[dict[str, Any]] = list(state.get("debate_rounds") or [])
    existing_rounds.append(round_entry)

    logger.info(
        "debate_loop_node: recorded round %d with %d agent response(s), "
        "bear_conviction=%d",
        round_number,
        len(agent_responses),
        bear_conviction,
    )

    return {"debate_rounds": existing_rounds, "current_node": NODE_DEBATE_LOOP}


debate_loop_node: _NodeFn = _persist_after(
    profile_node(_debate_loop_impl, NODE_DEBATE_LOOP), NODE_DEBATE_LOOP
)


def _valuation_impl(state: InvestmentState) -> dict[str, Any]:
    """
    Delegate to the real Valuation Agent (T-039).

    run_valuation_analysis fetches financials, ratios, and Screener.in
    peer data, runs a DCF, and returns the 'valuation' dict.
    """
    partial: dict[str, Any] = run_valuation_analysis(state)
    partial["current_node"] = NODE_VALUATION
    return partial


valuation_node: _NodeFn = _persist_after(
    profile_node(_valuation_impl, NODE_VALUATION), NODE_VALUATION
)


def _portfolio_manager_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = run_portfolio_manager_decision(state)
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_PORTFOLIO_MANAGER
    return partial


portfolio_manager_node: _NodeFn = _persist_after(
    profile_node(_portfolio_manager_impl, NODE_PORTFOLIO_MANAGER),
    NODE_PORTFOLIO_MANAGER,
)


def _report_generator_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = generate_investment_memo(_state_as_plain_dict(state))
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_REPORT_GENERATOR
    return partial


report_generator_node: _NodeFn = _persist_after(
    profile_node(_report_generator_impl, NODE_REPORT_GENERATOR),
    NODE_REPORT_GENERATOR,
)


def _pdf_export_impl(state: InvestmentState) -> dict[str, Any]:
    partial: dict[str, Any] = _pdf_export_node(_state_as_plain_dict(state))
    partial["status"] = "completed"
    partial["completed_at"] = datetime.utcnow().isoformat() + "Z"
    partial["current_node"] = NODE_PDF_EXPORT
    return partial


pdf_export_node: _NodeFn = _persist_after(
    profile_node(_pdf_export_impl, NODE_PDF_EXPORT),
    NODE_PDF_EXPORT,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Node name constants
    "NODE_PLANNER",
    "NODE_FUNDAMENTAL",
    "NODE_TECHNICAL",
    "NODE_SENTIMENT",
    "NODE_MACRO",
    "NODE_RESEARCH_JOIN",
    "NODE_ERROR_HANDLER",
    "NODE_SENTIMENT_ESCALATION",
    "NODE_RISK",
    "NODE_CONTRARIAN",
    "NODE_DEBATE_LOOP",
    "NODE_VALUATION",
    "NODE_PORTFOLIO_MANAGER",
    "NODE_REPORT_GENERATOR",
    "NODE_PDF_EXPORT",
    "NodeTimeoutError",
    # Node functions
    "planner_node",
    "fundamental_node",
    "technical_node",
    "sentiment_node",
    "macro_node",
    "research_join_node",
    "error_handler_node",
    "sentiment_escalation_node",
    "risk_node",
    "contrarian_node",
    "debate_loop_node",
    "valuation_node",
    "portfolio_manager_node",
    "report_generator_node",
    "pdf_export_node",
]
