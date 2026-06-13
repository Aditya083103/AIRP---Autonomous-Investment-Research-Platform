# backend/graph/graph.py
"""
AIRP -- LangGraph StateGraph with Conditional Routing (T-031 / T-032)

The AIRP investment analysis pipeline expressed as a LangGraph StateGraph.
T-032 extends T-031 to wire two conditional routing paths after the research
phase: an error handler for failed fundamental data, and a sentiment
escalation node for severely negative news environments.

Pipeline topology (T-032)
--------------------------

  START
    |
  [planner]                   validates state, sets status=running
    |
  route_after_planner()
    |-- ABORT -> END
    |-- list[Send] -> parallel fan-out:
         +-- [fundamental_analyst]  |
         +-- [technical_analyst]    | all 4 run concurrently
         +-- [sentiment_analyst]    | in the same super-step
         +-- [macro_economist]      |
                  |  (all 4 have direct edges to research_join)
                  v
         [research_join_node]      explicit sequential join choke-point
                  |
         route_after_research()    fires exactly ONCE here
                  |
          +-- ROUTE_ERROR -> [error_handler] -> [contrarian_investor]
          +-- ROUTE_ESCALATE -> [sentiment_escalation] -> [contrarian_investor]
          +-- ROUTE_PROCEED -> [contrarian_investor]
                  |
         route_after_contrarian()
          +-- DEBATE_AGAIN -> [contrarian_investor]  (self-loop)
          +-- PROCEED -> [risk_officer]
                  |
         [risk_officer]             Phase 4 stub (T-039)
                  |
         [valuation_agent]          Phase 4 stub (T-041)
                  |
         [portfolio_manager]        Phase 4 stub (T-042)
                  |
                 END

Why research_join_node? (T-032 topology fix)
---------------------------------------------
In T-031, the 4 research nodes had direct edges to contrarian_investor.
T-032 needs to inspect research outputs and branch. A naive approach puts
conditional edges on each of the 4 research nodes -- but this fires
route_after_research 4 times in the same super-step, routing all 4 to
the same destination node simultaneously. Any state write from that
destination (including current_node from the next sequential node) fails
with InvalidUpdateError (LastValue channel, multiple writes in one step).

The correct LangGraph pattern: insert a single sequential node between
the parallel fan-out and the conditional branch. All 4 research nodes
have DIRECT edges to research_join_node. LangGraph's implicit join
barrier ensures research_join_node runs only after all 4 complete.
The conditional edge is then attached to research_join_node alone.
route_after_research fires exactly once, in its own sequential step.

This is 12 nodes total:
  planner, fundamental, technical, sentiment, macro,
  research_join, error_handler, sentiment_escalation,
  contrarian, risk, valuation, portfolio_manager

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare type: ignore -- use cast() and explicit annotations.
* ``build_graph()`` is a factory function so tests can call it
  multiple times without state leaking between runs.
* ``get_compiled_graph()`` is an lru_cache singleton for production.

Public API
----------
    from backend.graph.graph import (
        build_graph,
        get_compiled_graph,
        PARALLEL_OVERHEAD_S,
        RESEARCH_NODE_NAMES,
        ROUTING_NODE_NAMES,
    )
"""

from functools import lru_cache
import logging
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from backend.graph.nodes import (
    NODE_CONTRARIAN,
    NODE_ERROR_HANDLER,
    NODE_FUNDAMENTAL,
    NODE_MACRO,
    NODE_PLANNER,
    NODE_PORTFOLIO_MANAGER,
    NODE_RESEARCH_JOIN,
    NODE_RISK,
    NODE_SENTIMENT,
    NODE_SENTIMENT_ESCALATION,
    NODE_TECHNICAL,
    NODE_VALUATION,
    contrarian_node,
    error_handler_node,
    fundamental_node,
    macro_node,
    planner_node,
    portfolio_manager_node,
    research_join_node,
    risk_node,
    sentiment_escalation_node,
    sentiment_node,
    technical_node,
    valuation_node,
)
from backend.graph.routing import (
    ROUTE_DEBATE_AGAIN,
    ROUTE_ERROR,
    ROUTE_ESCALATE_SENTIMENT,
    ROUTE_PROCEED,
    route_after_contrarian,
    route_after_planner,
    route_after_research,
)
from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum acceptable overhead (seconds) for parallel scheduling and
#: state merging, above the slowest individual agent runtime.
PARALLEL_OVERHEAD_S: float = 5.0

#: All 4 research agent node names -- used for logging and test assertions.
RESEARCH_NODE_NAMES: tuple[str, ...] = (
    NODE_FUNDAMENTAL,
    NODE_TECHNICAL,
    NODE_SENTIMENT,
    NODE_MACRO,
)

#: T-032 routing node names (join + error handler + escalation).
ROUTING_NODE_NAMES: tuple[str, ...] = (
    NODE_RESEARCH_JOIN,
    NODE_ERROR_HANDLER,
    NODE_SENTIMENT_ESCALATION,
)

# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """
    Build and compile the AIRP LangGraph StateGraph.

    Creates a fresh StateGraph, registers all 12 nodes, and wires:
    - T-031 Send API parallel fan-out: planner -> 4 research agents
    - T-032 explicit join: 4 research agents -> research_join_node
    - T-032 conditional routing: research_join -> error_handler OR
      sentiment_escalation OR contrarian (based on route_after_research)
    - Forward edges: error_handler -> contrarian, sentiment_escalation
      -> contrarian
    - Debate loop: contrarian -> route_after_contrarian -> contrarian OR risk
    - Sequential tail: risk -> valuation -> portfolio_manager -> END

    Returns:
        A compiled LangGraph CompiledGraph object.

    Raises:
        ValueError: If LangGraph detects unreachable nodes or invalid edges.
    """
    # -- 1. Initialise the StateGraph -------------------------------------
    workflow: StateGraph = StateGraph(InvestmentState)

    # -- 2. Register all 12 nodes -----------------------------------------
    workflow.add_node(NODE_PLANNER, planner_node)
    workflow.add_node(NODE_FUNDAMENTAL, fundamental_node)
    workflow.add_node(NODE_TECHNICAL, technical_node)
    workflow.add_node(NODE_SENTIMENT, sentiment_node)
    workflow.add_node(NODE_MACRO, macro_node)
    # T-032: explicit join + routing nodes
    workflow.add_node(NODE_RESEARCH_JOIN, research_join_node)
    workflow.add_node(NODE_ERROR_HANDLER, error_handler_node)
    workflow.add_node(NODE_SENTIMENT_ESCALATION, sentiment_escalation_node)
    # Phase 4 stubs
    workflow.add_node(NODE_CONTRARIAN, contrarian_node)
    workflow.add_node(NODE_RISK, risk_node)
    workflow.add_node(NODE_VALUATION, valuation_node)
    workflow.add_node(NODE_PORTFOLIO_MANAGER, portfolio_manager_node)

    # -- 3. Entry: START -> planner ---------------------------------------
    workflow.add_edge(START, NODE_PLANNER)

    # -- 4. planner -> Send fan-out OR END (abort) ------------------------
    workflow.add_conditional_edges(
        NODE_PLANNER,
        cast(Any, route_after_planner),
        {
            "__end__": END,
            # Reachability declarations for Send targets (T-031 pattern).
            NODE_FUNDAMENTAL: NODE_FUNDAMENTAL,
            NODE_TECHNICAL: NODE_TECHNICAL,
            NODE_SENTIMENT: NODE_SENTIMENT,
            NODE_MACRO: NODE_MACRO,
        },
    )

    # -- 5. Research agents -> research_join (direct edges, T-032) --------
    #
    # In T-031 these pointed directly at contrarian_investor.
    # In T-032 they point at research_join_node instead, giving us a
    # single sequential step where we can apply conditional routing.
    workflow.add_edge(NODE_FUNDAMENTAL, NODE_RESEARCH_JOIN)
    workflow.add_edge(NODE_TECHNICAL, NODE_RESEARCH_JOIN)
    workflow.add_edge(NODE_SENTIMENT, NODE_RESEARCH_JOIN)
    workflow.add_edge(NODE_MACRO, NODE_RESEARCH_JOIN)

    # -- 6. research_join -> conditional routing (T-032) ------------------
    #
    # route_after_research fires exactly ONCE here (single sequential step)
    # instead of 4 times (one per research node), avoiding InvalidUpdateError.
    workflow.add_conditional_edges(
        NODE_RESEARCH_JOIN,
        route_after_research,
        {
            ROUTE_ERROR: NODE_ERROR_HANDLER,
            ROUTE_ESCALATE_SENTIMENT: NODE_SENTIMENT_ESCALATION,
            ROUTE_PROCEED: NODE_CONTRARIAN,
        },
    )

    # -- 7. Routing nodes -> contrarian (T-032 forward edges) -------------
    workflow.add_edge(NODE_ERROR_HANDLER, NODE_CONTRARIAN)
    workflow.add_edge(NODE_SENTIMENT_ESCALATION, NODE_CONTRARIAN)

    # -- 8. Contrarian -> debate loop or risk -----------------------------
    workflow.add_conditional_edges(
        NODE_CONTRARIAN,
        route_after_contrarian,
        {
            ROUTE_DEBATE_AGAIN: NODE_CONTRARIAN,
            ROUTE_PROCEED: NODE_RISK,
        },
    )

    # -- 9. Sequential tail: risk -> valuation -> portfolio -> END --------
    workflow.add_edge(NODE_RISK, NODE_VALUATION)
    workflow.add_edge(NODE_VALUATION, NODE_PORTFOLIO_MANAGER)
    workflow.add_edge(NODE_PORTFOLIO_MANAGER, END)

    # -- 10. Compile -------------------------------------------------------
    compiled: Any = workflow.compile()
    logger.info(
        "build_graph: AIRP StateGraph compiled -- %d research agents, "
        "%d routing nodes, 12 total nodes",
        len(RESEARCH_NODE_NAMES),
        len(ROUTING_NODE_NAMES),
    )
    return compiled


# ---------------------------------------------------------------------------
# Production singleton
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_compiled_graph() -> Any:
    """
    Return the compiled AIRP graph as a singleton (lru_cache).

    In tests, call ``build_graph()`` directly to avoid cache pollution.

    Returns:
        The compiled LangGraph CompiledGraph singleton.
    """
    return build_graph()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "build_graph",
    "get_compiled_graph",
    "PARALLEL_OVERHEAD_S",
    "RESEARCH_NODE_NAMES",
    "ROUTING_NODE_NAMES",
]
