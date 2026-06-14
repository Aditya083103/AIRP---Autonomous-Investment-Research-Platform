# backend/graph/nodes.py
"""
AIRP -- LangGraph Node Functions (T-030 / T-031 / T-032 / T-033)

Thin wrapper functions that adapt each agent's public API to the
LangGraph node contract: receive InvestmentState, return a partial
dict that LangGraph merges back into state.

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

T-032 topology (unchanged):
    [fundamental]  --|
    [technical]    --+--> [research_join] --> route_after_research()
    [sentiment]    --|         |                    |
    [macro]        --|    ROUTE_ERROR -> [error_handler] -> [contrarian]
                          ROUTE_ESCALATE -> [sentiment_escalation] -> [contra]
                             ROUTE_PROCEED -> [contrarian]

T-033 persistence wrappers (sequential nodes only):
    planner_node, research_join_node, error_handler_node,
    sentiment_escalation_node, contrarian_node, risk_node,
    valuation_node, portfolio_manager_node

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
        risk_node, contrarian_node, valuation_node,
        portfolio_manager_node,
    )
"""

import asyncio
from datetime import datetime
import logging
from typing import Any, Callable

from backend.agents.fundamental_analyst import run_fundamental_analysis
from backend.agents.macro_economist import run_macro_analysis
from backend.agents.sentiment_analyst import run_sentiment_analysis
from backend.agents.technical_analyst import run_technical_analysis
from backend.graph.state import InvestmentState

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
NODE_VALUATION = "valuation_agent"
NODE_PORTFOLIO_MANAGER = "portfolio_manager"

# ---------------------------------------------------------------------------
# T-033 persistence helper
# ---------------------------------------------------------------------------

_NodeFn = Callable[[InvestmentState], dict[str, Any]]


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


planner_node: _NodeFn = _persist_after(_planner_node_impl, NODE_PLANNER)

# ---------------------------------------------------------------------------
# Phase 2 research agent nodes -- NOT wrapped (parallel super-step)
# ---------------------------------------------------------------------------


def fundamental_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Fundamental Analyst agent.

    NOT persistence-wrapped: runs in the Send super-step alongside
    3 other research nodes.  Persistence happens in research_join_node.

    Returns:
        Partial state dict: ``{"fundamental": <model_dump dict>}``.
    """
    logger.info(
        "fundamental_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return run_fundamental_analysis(state)


def technical_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Technical Analyst agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Returns:
        Partial state dict: ``{"technical": <model_dump dict>}``.
    """
    logger.info(
        "technical_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return run_technical_analysis(state)


def sentiment_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the News Sentiment Agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Returns:
        Partial state dict: ``{"sentiment": <model_dump dict>}``.
    """
    logger.info(
        "sentiment_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return run_sentiment_analysis(state)


def macro_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Macro Economist agent.

    NOT persistence-wrapped: parallel super-step constraint.

    Returns:
        Partial state dict: ``{"macro": <model_dump dict>}``.
    """
    logger.info(
        "macro_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    return run_macro_analysis(state)


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


research_join_node: _NodeFn = _persist_after(_research_join_impl, NODE_RESEARCH_JOIN)

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


error_handler_node: _NodeFn = _persist_after(_error_handler_impl, NODE_ERROR_HANDLER)


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
    _sentiment_escalation_impl, NODE_SENTIMENT_ESCALATION
)

# ---------------------------------------------------------------------------
# Phase 4 stub nodes -- persistence-wrapped stubs
# ---------------------------------------------------------------------------


def _risk_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info("risk_node: STUB -- Risk Officer not yet implemented (T-039)")
    return {
        "risk": {
            "agent_name": "risk_officer",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": "not_implemented: risk_officer stub (T-039)",
            "risk_score": 5,
            "governance_risk": 5,
            "regulatory_risk": 5,
            "financial_risk": 5,
            "concentration_risk": 5,
            "risk_flags": [],
            "critical_flags": [],
            "risk_recommendation": "pending",
            "summary": "Risk Officer stub -- full analysis in T-039.",
        },
        "current_node": NODE_RISK,
    }


risk_node: _NodeFn = _persist_after(_risk_impl, NODE_RISK)


def _contrarian_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info(
        "contrarian_node: STUB -- Contrarian Investor not yet implemented (T-040)"
    )
    return {
        "contrarian": {
            "agent_name": "contrarian_investor",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": "not_implemented: contrarian_investor stub (T-040)",
            "counter_arguments": [],
            "challenged_agents": [],
            "overlooked_risks": [],
            "bear_conviction": 1,
            "strongest_argument": "Contrarian stub -- full analysis in T-040.",
            "summary": "Contrarian Investor stub -- full analysis in T-040.",
        },
        "current_node": NODE_CONTRARIAN,
    }


contrarian_node: _NodeFn = _persist_after(_contrarian_impl, NODE_CONTRARIAN)


def _valuation_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info("valuation_node: STUB -- Valuation Agent not yet implemented (T-041)")
    return {
        "valuation": {
            "agent_name": "valuation_agent",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": "not_implemented: valuation_agent stub (T-041)",
            "valuation_verdict": "fairly_valued",
            "peer_tickers": [],
            "summary": "Valuation Agent stub -- full analysis in T-041.",
        },
        "current_node": NODE_VALUATION,
    }


valuation_node: _NodeFn = _persist_after(_valuation_impl, NODE_VALUATION)


def _portfolio_manager_impl(state: InvestmentState) -> dict[str, Any]:
    logger.info(
        "portfolio_manager_node: STUB -- Portfolio Manager not yet "
        "implemented (T-042)"
    )
    return {
        "decision": {
            "agent_name": "portfolio_manager",
            "analysis_id": state.get("job_id", "unknown"),
            "company_name": state.get("company_name", "unknown"),
            "ticker": state.get("ticker", "unknown"),
            "error": "not_implemented: portfolio_manager stub (T-042)",
            "verdict": "HOLD",
            "conviction_score": 5,
            "debate_rounds_used": state.get("debate_round_count", 0),
            "agent_weights": {},
            "summary": "Portfolio Manager stub -- full analysis in T-042.",
        },
        "final_verdict": "HOLD",
        "conviction_score": 5,
        "status": "completed",
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "current_node": NODE_PORTFOLIO_MANAGER,
    }


portfolio_manager_node: _NodeFn = _persist_after(
    _portfolio_manager_impl, NODE_PORTFOLIO_MANAGER
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
    "NODE_VALUATION",
    "NODE_PORTFOLIO_MANAGER",
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
    "valuation_node",
    "portfolio_manager_node",
]
