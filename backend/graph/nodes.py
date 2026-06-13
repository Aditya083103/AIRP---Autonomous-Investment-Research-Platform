# backend/graph/nodes.py
"""
AIRP -- LangGraph Node Functions (T-030 / T-031 / T-032)

Thin wrapper functions that adapt each agent's public API to the
LangGraph node contract: receive InvestmentState, return a partial
dict that LangGraph merges back into state.

Architecture
------------
Every node function follows the same pattern::

    def node_name(state: InvestmentState) -> dict[str, Any]:
        ...
        return {"field": value}

LangGraph merges the returned dict into the current state automatically.
Nodes never receive the entire state to overwrite -- they return only
the keys they own.

T-032 additions (conditional routing logic)
-------------------------------------------
The key topology insight (T-032):

In T-031, all 4 research nodes had direct edges to contrarian_investor.
LangGraph's implicit join barrier meant contrarian waited for all 4.

In T-032, we want to inspect research outputs and branch AFTER the join.
The problem: if we put conditional edges on each of the 4 research nodes,
route_after_research fires 4 times in the same super-step -> 4 writes to
the same destination node in one step -> InvalidUpdateError on any channel
that destination writes.

Solution: introduce ``research_join_node`` as an explicit join choke-point.
All 4 research agents have direct edges -> research_join_node.
research_join_node runs SEQUENTIALLY (one step, after the join barrier).
The conditional edge sits on research_join_node alone, so route_after_research
fires exactly once, and only one destination node is chosen per step.

Node flow:
    [fundamental]  --|
    [technical]    --+--> [research_join] --> route_after_research()
    [sentiment]    --|         |                    |
    [macro]        --|         |        ROUTE_ERROR -> [error_handler] -> [contrarian]
                               |  ROUTE_ESCALATE -> [sentiment_escalation] -> [contra]
                               |       ROUTE_PROCEED -> [contrarian]

research_join_node
    Explicit join node. Receives state after all 4 research agents have
    written their outputs. Does nothing itself -- just provides a single
    sequential choke-point so route_after_research fires exactly once.
    Sets current_node = NODE_RESEARCH_JOIN for LangSmith tracing.

error_handler_node
    Receives control when route_after_research detects fundamental["error"]
    is non-null. Writes degraded-pipeline flags. Forwards to contrarian.
    CAN now safely set current_node because it runs in its own step.

sentiment_escalation_node
    Receives control when sentiment_score < -0.8. Writes escalation flag.
    Forwards to contrarian. CAN now safely set current_node.

Phase 2 nodes (implemented -- T-022 to T-025)
----------------------------------------------
planner_node          -- validates state, sets pipeline status
fundamental_node      -- delegates to run_fundamental_analysis()
technical_node        -- delegates to run_technical_analysis()
sentiment_node        -- delegates to run_sentiment_analysis()
macro_node            -- delegates to run_macro_analysis()

Phase 3 nodes (T-031 / T-032)
------------------------------
research_join_node        -- explicit join after parallel research (T-032)
error_handler_node        -- handles fetch_financials empty (T-032)
sentiment_escalation_node -- flags severe negative sentiment (T-032)

Phase 4 stub nodes (skeleton -- logic added in T-037 to T-044)
---------------------------------------------------------------
risk_node             -- Risk Officer agent (T-039)
contrarian_node       -- Contrarian Investor agent (T-040)
valuation_node        -- Valuation Agent (T-041)
portfolio_manager_node -- Portfolio Manager + memo (T-042/T-043)

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule
  that prevents Pydantic v2 union breakage.

* Plain ASCII section comments (# ---) -- avoids flake8 E501 from
  Unicode box-drawing chars (established rule from T-024 onward).

* No bare type: ignore -- use cast() and explicit annotations.

* research_join_node is the correct LangGraph pattern for "branch after
  parallel join". The conditional edge belongs on the join node, not on
  each of the 4 parallel nodes.

Public API
----------
    from backend.graph.nodes import (
        planner_node,
        fundamental_node,
        technical_node,
        sentiment_node,
        macro_node,
        research_join_node,
        error_handler_node,
        sentiment_escalation_node,
        risk_node,
        contrarian_node,
        valuation_node,
        portfolio_manager_node,
    )
"""

from datetime import datetime
import logging
from typing import Any

from backend.agents.fundamental_analyst import run_fundamental_analysis
from backend.agents.macro_economist import run_macro_analysis
from backend.agents.sentiment_analyst import run_sentiment_analysis
from backend.agents.technical_analyst import run_technical_analysis
from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node name constants -- single source of truth used by graph.py and tests
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
# Planner node -- pipeline entry point
# ---------------------------------------------------------------------------


def planner_node(state: InvestmentState) -> dict[str, Any]:
    """
    Pipeline entry point -- validates state and sets running status.

    Verifies that ``ticker`` and ``company_name`` are present, sets
    ``status`` to ``"running"`` and records ``started_at``.

    Args:
        state: Current InvestmentState from LangGraph.

    Returns:
        Partial state dict with status, current_node, and started_at.
        Returns status="failed" with pipeline_error when validation fails.
    """
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


# ---------------------------------------------------------------------------
# Phase 2 research agent nodes -- delegate to real implementations
# ---------------------------------------------------------------------------


def fundamental_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Fundamental Analyst agent.

    Delegates directly to ``run_fundamental_analysis()`` which handles
    all error cases internally and never raises.

    Note: current_node is NOT set -- parallel super-step constraint.
    All 4 research agents run in the same super-step via Send API;
    writing current_node from multiple nodes raises InvalidUpdateError.

    Args:
        state: Current InvestmentState. Dispatched via Send API (T-031).

    Returns:
        Partial state dict: ``{"fundamental": <model_dump dict>}``.
    """
    logger.info(
        "fundamental_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_fundamental_analysis(state)
    return result


def technical_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Technical Analyst agent.

    Note: current_node is NOT set -- parallel super-step constraint.

    Args:
        state: Current InvestmentState. Dispatched via Send API (T-031).

    Returns:
        Partial state dict: ``{"technical": <model_dump dict>}``.
    """
    logger.info(
        "technical_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_technical_analysis(state)
    return result


def sentiment_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the News Sentiment Agent.

    Note: current_node is NOT set -- parallel super-step constraint.

    Args:
        state: Current InvestmentState. Dispatched via Send API (T-031).

    Returns:
        Partial state dict: ``{"sentiment": <model_dump dict>}``.
    """
    logger.info(
        "sentiment_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_sentiment_analysis(state)
    return result


def macro_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Macro Economist agent.

    Note: current_node is NOT set -- parallel super-step constraint.

    Args:
        state: Current InvestmentState. Dispatched via Send API (T-031).

    Returns:
        Partial state dict: ``{"macro": <model_dump dict>}``.
    """
    logger.info(
        "macro_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_macro_analysis(state)
    return result


# ---------------------------------------------------------------------------
# T-032 join node -- explicit sequential choke-point after parallel research
# ---------------------------------------------------------------------------


def research_join_node(state: InvestmentState) -> dict[str, Any]:
    """
    Explicit join node after parallel research execution (T-032).

    All 4 research nodes have direct edges to this node.  LangGraph's
    Pregel runtime uses incoming edge count as a barrier: this node runs
    only after all 4 research agents have completed and merged their
    partial state updates.

    This node is intentionally a passthrough -- it does no computation.
    Its sole purpose is to provide a single sequential step where
    route_after_research can fire exactly once (instead of 4 times from
    4 separate conditional edges on the research nodes, which would cause
    InvalidUpdateError).

    The conditional edge is attached here, not on the individual research
    nodes. This is the correct LangGraph pattern for "branch after parallel
    join".

    Args:
        state: Fully-merged InvestmentState after all 4 research agents ran.

    Returns:
        Partial state dict setting current_node for LangSmith tracing.
    """
    ticker: str = state.get("ticker", "unknown")
    logger.info(
        "research_join_node: all 4 research agents complete for %s -- "
        "evaluating routing conditions",
        ticker,
    )
    return {"current_node": NODE_RESEARCH_JOIN}


# ---------------------------------------------------------------------------
# T-032 routing nodes -- error handler and sentiment escalation
# ---------------------------------------------------------------------------


def error_handler_node(state: InvestmentState) -> dict[str, Any]:
    """
    Error handler node for failed fundamental data fetch (T-032).

    Receives control when ``route_after_research`` (on research_join_node)
    detects that ``fundamental["error"]`` is non-null.

    This node does NOT terminate the pipeline.  It marks the pipeline as
    degraded and writes flags so downstream agents apply maximum caution.
    After this node, the graph forwards to the contrarian node.

    Because this node is reached from research_join_node (a single
    sequential node, not 4 parallel ones), it runs in its own step and
    can safely write current_node.

    Args:
        state: Current InvestmentState.

    Returns:
        Partial state dict with pipeline_error, risk_flags, critical_flags,
        and current_node.
    """
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


def sentiment_escalation_node(state: InvestmentState) -> dict[str, Any]:
    """
    Sentiment escalation node for severely negative news environment (T-032).

    Receives control when ``route_after_research`` (on research_join_node)
    detects ``sentiment["sentiment_score"] < -0.8``.

    Appends ESCALATION_FLAG_NEGATIVE_SENTIMENT to risk_flags and
    critical_flags.  Forwards to contrarian node.

    Because this node is reached from research_join_node (a single
    sequential node), it runs in its own step and can safely write
    current_node.

    Args:
        state: Current InvestmentState.

    Returns:
        Partial state dict with risk_flags, critical_flags, current_node.
    """
    from backend.graph.routing import (  # noqa: PLC0415 -- local to avoid cycle
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


# ---------------------------------------------------------------------------
# Phase 4 stub nodes -- skeleton only; real logic added in T-037 to T-044
# ---------------------------------------------------------------------------


def risk_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Risk Officer agent (implemented in T-039).

    Args:
        state: Current InvestmentState after debate loop completion.

    Returns:
        Partial state dict with sentinel ``risk`` output.
    """
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


def contrarian_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Contrarian Investor agent (implemented in T-040).

    Args:
        state: Current InvestmentState after research agents complete.

    Returns:
        Partial state dict with sentinel ``contrarian`` output.
    """
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


def valuation_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Valuation Agent (implemented in T-041).

    Args:
        state: Current InvestmentState after debate and risk assessment.

    Returns:
        Partial state dict with sentinel ``valuation`` output.
    """
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


def portfolio_manager_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Portfolio Manager agent (implemented in T-042/T-043).

    Args:
        state: Fully-populated InvestmentState (all agents complete).

    Returns:
        Partial state dict with sentinel ``decision`` output and
        pipeline completion metadata.
    """
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
