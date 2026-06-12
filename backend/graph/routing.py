# backend/graph/routing.py
"""
AIRP -- LangGraph Conditional Edge Functions (T-030 / T-031)

Conditional edge functions determine which node executes next based
on the current state. LangGraph calls these on edges that need runtime
branching -- routing to error handling when an agent fails, deciding
whether another debate round is needed, or fanning out to parallel
research agents via the Send API.

Routing functions
-----------------
route_after_planner
    After the Planner node: dispatch 4 research agents in parallel via
    Send API (T-031), or abort to END if the Planner detected a fatal
    configuration error.

route_after_research
    After all 4 research agents complete (implicit join): proceed to
    the contrarian node. In Phase 4 this will detect all-agent failures.

route_after_contrarian
    After the Contrarian Investor node: decide whether to run another
    debate round (bear_conviction >= 7) or proceed to Risk + Valuation.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.

* Plain ASCII section comments (# ---) -- avoids flake8 E501 from
  Unicode box-drawing chars (rule from T-024 onward).

* route_after_planner returns a list[Send] on the PROCEED path,
  not a plain str. LangGraph dispatches each Send object concurrently,
  giving true parallel execution of the 4 research agents (T-031).

* On the ABORT path, route_after_planner returns the END sentinel
  string so LangGraph terminates the pipeline immediately.

* ROUTE_* constants are used for routing outcomes that are plain str
  (the abort path and the post-research / post-contrarian paths).
  The parallel fan-out path returns List[Send] directly.

* All routing functions use state.get() with defaults -- they must
  never raise, even on partially-populated state.

Public API
----------
    from backend.graph.routing import (
        ROUTE_PROCEED,
        ROUTE_ABORT,
        ROUTE_DEBATE_AGAIN,
        route_after_planner,
        route_after_research,
        route_after_contrarian,
    )
"""

import logging
from typing import Any, Union

from langgraph.graph import END
from langgraph.types import Send

from backend.graph.nodes import (
    NODE_FUNDAMENTAL,
    NODE_MACRO,
    NODE_SENTIMENT,
    NODE_TECHNICAL,
)
from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route outcome string constants
# ---------------------------------------------------------------------------

#: Normal forward path (post-research and post-contrarian routing).
ROUTE_PROCEED = "proceed"

#: Abort -- route directly to END without further agent calls.
ROUTE_ABORT = "abort"

#: Run another debate round (bear_conviction >= 7 threshold).
ROUTE_DEBATE_AGAIN = "debate_again"

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

# The return type for route_after_planner is Union[str, list[Send]]
# because LangGraph accepts either:
#   - a str key that maps to a node name via the routing dict, or
#   - a list of Send objects for parallel fan-out
# mypy does not have stubs for langgraph, so we use the most precise
# annotation available: Union[str, list[Send]].

_PlannerRoute = Union[str, list[Send]]


def route_after_planner(state: InvestmentState) -> _PlannerRoute:
    """
    Conditional edge after the Planner node -- T-031 parallel fan-out.

    Routing logic:
    - ``status == "failed"`` -> return END (abort path; skip all agents)
    - Otherwise -> return ``[Send(node, state), ...]`` for all 4 research
      agents so LangGraph dispatches them concurrently in the same
      super-step.

    The Send API passes a copy of the current state to each target node.
    Each research node writes a different key (fundamental / technical /
    sentiment / macro) so their outputs merge without conflict.

    Args:
        state: Current InvestmentState after planner_node() ran.

    Returns:
        END string on abort, or list of Send objects for parallel dispatch.
    """
    pipeline_status: str = state.get("status", "pending")
    if pipeline_status == "failed":
        logger.warning(
            "route_after_planner: pipeline_error=%r -- aborting",
            state.get("pipeline_error"),
        )
        return END

    # Build a state snapshot to send to each research agent.
    # We pass the full state so each agent can read job_id, ticker,
    # company_name and any other fields it needs.
    state_dict: dict[str, Any] = dict(state)

    sends: list[Send] = [
        Send(NODE_FUNDAMENTAL, state_dict),
        Send(NODE_TECHNICAL, state_dict),
        Send(NODE_SENTIMENT, state_dict),
        Send(NODE_MACRO, state_dict),
    ]
    logger.info(
        "route_after_planner: dispatching %d research agents in parallel",
        len(sends),
    )
    return sends


def route_after_research(state: InvestmentState) -> str:
    """
    Conditional edge after all 4 research agents complete.

    LangGraph's implicit join barrier ensures this function is only
    called after all four inbound Send dispatches have finished.

    In Phase 3 (skeleton) this always returns ROUTE_PROCEED, sending
    the pipeline to the Contrarian node.

    In Phase 4 (T-037) this will inspect each agent's ``error`` field
    and route to an error-handling node if all four research agents
    failed simultaneously.

    Args:
        state: Current InvestmentState after all research agents ran.

    Returns:
        ROUTE_PROCEED (always in skeleton).
    """
    agents_with_errors: list[str] = []
    for field, name in [
        ("fundamental", "fundamental_analyst"),
        ("technical", "technical_analyst"),
        ("sentiment", "sentiment_analyst"),
        ("macro", "macro_economist"),
    ]:
        agent_out: Any = state.get(field)
        if isinstance(agent_out, dict) and agent_out.get("error"):
            agents_with_errors.append(name)

    if agents_with_errors:
        logger.warning(
            "route_after_research: %d agent(s) returned errors: %s -- "
            "proceeding anyway (Phase 4 adds abort on total failure)",
            len(agents_with_errors),
            agents_with_errors,
        )
    else:
        logger.info("route_after_research: all research agents completed cleanly")

    return ROUTE_PROCEED


def route_after_contrarian(state: InvestmentState) -> str:
    """
    Conditional edge after the Contrarian Investor node.

    Routing logic:
    - ``contrarian["bear_conviction"] >= 7`` AND rounds < 2
      -> ROUTE_DEBATE_AGAIN (the Contrarian is strongly contra-consensus)
    - Otherwise -> ROUTE_PROCEED (move to Risk Officer)

    In the skeleton (T-030/T-031) the contrarian stub always sets
    ``bear_conviction = 1``, so this will always route PROCEED.
    The actual debate loop logic is added in T-037/T-038.

    Args:
        state: Current InvestmentState after contrarian_node() ran.

    Returns:
        ROUTE_DEBATE_AGAIN or ROUTE_PROCEED string.
    """
    contrarian_out: Any = state.get("contrarian")
    debate_count: int = state.get("debate_round_count", 0)

    max_rounds: int = 2
    if debate_count >= max_rounds:
        logger.info(
            "route_after_contrarian: max debate rounds (%d) reached "
            "-- proceeding to risk/valuation",
            max_rounds,
        )
        return ROUTE_PROCEED

    bear_conviction: int = 1
    if isinstance(contrarian_out, dict):
        raw: Any = contrarian_out.get("bear_conviction", 1)
        if isinstance(raw, int):
            bear_conviction = raw

    if bear_conviction >= 7:
        logger.info(
            "route_after_contrarian: bear_conviction=%d >= 7 -- "
            "triggering another debate round",
            bear_conviction,
        )
        return ROUTE_DEBATE_AGAIN

    logger.info(
        "route_after_contrarian: bear_conviction=%d < 7 -- "
        "proceeding to risk/valuation",
        bear_conviction,
    )
    return ROUTE_PROCEED


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ROUTE_PROCEED",
    "ROUTE_ABORT",
    "ROUTE_DEBATE_AGAIN",
    "route_after_planner",
    "route_after_research",
    "route_after_contrarian",
]
