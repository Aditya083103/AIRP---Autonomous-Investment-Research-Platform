# backend/graph/nodes.py
"""
AIRP -- LangGraph Node Functions (T-030 / T-031)

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

Phase 2 nodes (implemented -- T-022 to T-025)
----------------------------------------------
planner_node          -- validates state, sets pipeline status
fundamental_node      -- delegates to run_fundamental_analysis()
technical_node        -- delegates to run_technical_analysis()
sentiment_node        -- delegates to run_sentiment_analysis()
macro_node            -- delegates to run_macro_analysis()

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

* Stub nodes return a sentinel output dict so the graph compiles and
  the Mermaid diagram is correct. Phase 4 tasks replace these stubs
  with real implementations.

* cast() used where mypy needs help narrowing dict[str, Any] access --
  no bare type: ignore comments anywhere in this file.

Public API
----------
    from backend.graph.nodes import (
        planner_node,
        fundamental_node,
        technical_node,
        sentiment_node,
        macro_node,
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

    In Phase 3 (T-031) the Planner feeds the parallel dispatcher which
    fans out to all four research agents simultaneously via Send API.

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

    Args:
        state: Current InvestmentState (must contain ticker, company_name,
               job_id). Dispatched via Send API in T-031 parallel execution.

    Returns:
        Partial state dict: ``{"fundamental": <model_dump dict>}``.
        Note: current_node is NOT set here -- all 4 research agents run in
        the same parallel super-step and LangGraph forbids multiple writes
        to the same key per step.
    """
    logger.info(
        "fundamental_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_fundamental_analysis(state)
    # Do NOT set current_node here: all 4 research agents run in the same
    # parallel super-step. Setting current_node from multiple nodes in one
    # step causes InvalidUpdateError (LangGraph LastValue channel conflict).
    return result


def technical_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Technical Analyst agent.

    Delegates directly to ``run_technical_analysis()`` which handles
    all error cases internally and never raises.

    Args:
        state: Current InvestmentState. Dispatched via Send API in T-031.

    Returns:
        Partial state dict: ``{"technical": <model_dump dict>}``.
        Note: current_node is NOT set -- parallel super-step constraint.
    """
    logger.info(
        "technical_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_technical_analysis(state)
    # Do NOT set current_node -- parallel super-step constraint.
    return result


def sentiment_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the News Sentiment Agent.

    Delegates directly to ``run_sentiment_analysis()`` which handles
    all error cases internally and never raises.

    Args:
        state: Current InvestmentState. Dispatched via Send API in T-031.

    Returns:
        Partial state dict: ``{"sentiment": <model_dump dict>}``.
        Note: current_node is NOT set -- parallel super-step constraint.
    """
    logger.info(
        "sentiment_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_sentiment_analysis(state)
    # Do NOT set current_node -- parallel super-step constraint.
    return result


def macro_node(state: InvestmentState) -> dict[str, Any]:
    """
    LangGraph node for the Macro Economist agent.

    Delegates directly to ``run_macro_analysis()`` which handles
    all error cases internally and never raises.

    Args:
        state: Current InvestmentState. Dispatched via Send API in T-031.

    Returns:
        Partial state dict: ``{"macro": <model_dump dict>}``.
        Note: current_node is NOT set -- parallel super-step constraint.
    """
    logger.info(
        "macro_node: running for ticker=%s",
        state.get("ticker", "unknown"),
    )
    result: dict[str, Any] = run_macro_analysis(state)
    # Do NOT set current_node -- parallel super-step constraint.
    return result


# ---------------------------------------------------------------------------
# Phase 4 stub nodes -- skeleton only; real logic added in T-037 to T-044
# ---------------------------------------------------------------------------


def risk_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Risk Officer agent (implemented in T-039).

    Reads all prior research agent outputs and the debate transcript to
    identify governance failures, fraud indicators, regulatory risks,
    and concentration risks.

    Current behaviour (skeleton): returns a sentinel output dict with
    ``error="not_implemented"`` so the graph compiles and downstream
    nodes can still run.

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

    Its only job: disagree. Finds flaws in every bullish thesis.

    Current behaviour (skeleton): returns a sentinel output dict so
    the graph compiles correctly.

    Args:
        state: Current InvestmentState after research agents complete.

    Returns:
        Partial state dict with sentinel ``contrarian`` output.
    """
    logger.info(
        "contrarian_node: STUB -- Contrarian Investor not yet " "implemented (T-040)"
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
            "strongest_argument": ("Contrarian stub -- full analysis in T-040."),
            "summary": ("Contrarian Investor stub -- full analysis in T-040."),
        },
        "current_node": NODE_CONTRARIAN,
    }


def valuation_node(state: InvestmentState) -> dict[str, Any]:
    """
    Stub for the Valuation Agent (implemented in T-041).

    Runs a DCF valuation model and compares PE/PB/EV-EBITDA against
    sector peers.

    Current behaviour (skeleton): returns a sentinel output dict so
    the graph compiles correctly.

    Args:
        state: Current InvestmentState after debate and risk assessment.

    Returns:
        Partial state dict with sentinel ``valuation`` output.
    """
    logger.info(
        "valuation_node: STUB -- Valuation Agent not yet " "implemented (T-041)"
    )
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

    Reads the complete InvestmentState and delivers the final
    BUY/HOLD/SELL verdict with a conviction score and memo.

    Current behaviour (skeleton): returns a sentinel output dict so
    the graph compiles and can reach END.

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
    "risk_node",
    "contrarian_node",
    "valuation_node",
    "portfolio_manager_node",
]
