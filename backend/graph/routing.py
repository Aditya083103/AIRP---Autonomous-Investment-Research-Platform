# backend/graph/routing.py
"""
AIRP -- LangGraph Conditional Edge Functions (T-030)

Conditional edge functions determine which node executes next based
on the current state.  LangGraph calls these functions on edges that
need runtime branching -- for example, routing to error handling when
an agent fails, or deciding whether to run another debate round.

Routing functions in this module
---------------------------------
route_after_planner
    After the Planner node: proceed to research agents or abort to END
    if the Planner detected a fatal configuration error.

route_after_research
    After all 4 research agents complete: proceed to the debate/contrarian
    node.  In Phase 4 this will check whether any research agent returned
    an error and route accordingly.

route_after_contrarian
    After the Contrarian Investor node: decide whether to run another
    debate round (bear_conviction >= 7) or proceed to Risk + Valuation.
    In the skeleton this always routes forward (no loop yet -- added T-038).

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.

* Plain ASCII section comments (# ---) -- avoids flake8 E501 from
  Unicode box-drawing chars (rule from T-024 onward).

* Routing functions return ``str`` (node name) or ``list[str]``.
  LangGraph uses the return value to select the next node via the
  mapping provided in ``add_conditional_edges()``.

* All routing functions use ``state.get()`` with defaults -- they must
  never raise, even on partially-populated state.

* The ROUTE_* string constants are the canonical values returned by
  routing functions and used as keys in the edge mapping dicts passed
  to ``add_conditional_edges()``.  They are the single source of truth
  for routing outcome names.

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
from typing import Any

from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route outcome string constants -- used as keys in edge mapping dicts
# ---------------------------------------------------------------------------

#: Normal forward path through the pipeline.
ROUTE_PROCEED = "proceed"

#: Abort the pipeline; route directly to END without further agent calls.
ROUTE_ABORT = "abort"

#: Run another debate round (bear_conviction >= 7 threshold).
ROUTE_DEBATE_AGAIN = "debate_again"

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_after_planner(state: InvestmentState) -> str:
    """
    Conditional edge after the Planner node.

    Routing logic:
    - ``status == "failed"`` (Planner detected missing ticker/company)
      -> ROUTE_ABORT  (skip all agents, go straight to END)
    - Otherwise -> ROUTE_PROCEED  (fan out to 4 parallel research agents)

    Args:
        state: Current InvestmentState after planner_node() ran.

    Returns:
        ROUTE_ABORT or ROUTE_PROCEED string.
    """
    status: str = state.get("status", "pending")
    if status == "failed":
        logger.warning(
            "route_after_planner: pipeline_error=%r -- aborting",
            state.get("pipeline_error"),
        )
        return ROUTE_ABORT
    logger.info("route_after_planner: proceeding to research agents")
    return ROUTE_PROCEED


def route_after_research(state: InvestmentState) -> str:
    """
    Conditional edge after all 4 research agents complete.

    In Phase 3 (skeleton) this always returns ROUTE_PROCEED, sending
    the pipeline to the Contrarian node.

    In Phase 4 (T-037) this will inspect each agent's ``error`` field
    and route to an error-handling node if all four research agents
    failed (catastrophic data failure).

    Args:
        state: Current InvestmentState after all research agents ran.

    Returns:
        ROUTE_PROCEED (always in skeleton).
    """
    # Skeleton: proceed regardless of individual agent errors.
    # Phase 4 will add: if all four agents errored -> ROUTE_ABORT.
    _agents_with_errors: list[str] = []
    for field, name in [
        ("fundamental", "fundamental_analyst"),
        ("technical", "technical_analyst"),
        ("sentiment", "sentiment_analyst"),
        ("macro", "macro_economist"),
    ]:
        agent_out: Any = state.get(field)
        if isinstance(agent_out, dict) and agent_out.get("error"):
            _agents_with_errors.append(name)

    if _agents_with_errors:
        logger.warning(
            "route_after_research: %d agent(s) returned errors: %s -- "
            "proceeding anyway (Phase 4 will add abort logic)",
            len(_agents_with_errors),
            _agents_with_errors,
        )
    else:
        logger.info("route_after_research: all research agents completed cleanly")

    return ROUTE_PROCEED


def route_after_contrarian(state: InvestmentState) -> str:
    """
    Conditional edge after the Contrarian Investor node.

    Routing logic (Phase 4 implementation):
    - ``contrarian["bear_conviction"] >= 7`` -> ROUTE_DEBATE_AGAIN
      (the Contrarian is strongly contra-consensus; run another round)
    - Otherwise -> ROUTE_PROCEED  (move to Risk Officer)

    In the skeleton (T-030) the contrarian stub always sets
    ``bear_conviction = 1``, so this will always route PROCEED.
    The actual debate loop logic is added in T-037/T-038.

    Args:
        state: Current InvestmentState after contrarian_node() ran.

    Returns:
        ROUTE_DEBATE_AGAIN or ROUTE_PROCEED string.
    """
    contrarian_out: Any = state.get("contrarian")
    debate_count: int = state.get("debate_round_count", 0)

    # Hard cap: never exceed 2 debate rounds regardless of conviction.
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
