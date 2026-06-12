# backend/graph/graph.py
"""
AIRP -- LangGraph StateGraph Definition (T-030)

The AIRP investment analysis pipeline expressed as a LangGraph StateGraph.
This module is the orchestration brain: it wires all 8 agent nodes,
defines edges (sequential and parallel), and compiles the graph into a
runnable Pregel object.

Pipeline topology (Phase 3 skeleton)
--------------------------------------

  START
    |
  [planner]                  -- validates state, sets status=running
    |
  route_after_planner()
    |  PROCEED                ABORT
    |                          |
    +-- [fundamental_analyst]  END
    +-- [technical_analyst]
    +-- [sentiment_analyst]
    +-- [macro_economist]      (all 4 run in parallel via Send API)
    |
  route_after_research()
    | PROCEED
    |
  [contrarian_investor]       -- Phase 4 stub (T-040)
    |
  route_after_contrarian()
    | PROCEED          DEBATE_AGAIN
    |                    (back to contrarian -- loop, max 2 rounds)
  [risk_officer]              -- Phase 4 stub (T-039)
    |
  [valuation_agent]           -- Phase 4 stub (T-041)
    |
  [portfolio_manager]         -- Phase 4 stub (T-042)
    |
  END

LangGraph 0.2.x API used
--------------------------
- ``StateGraph(InvestmentState)``   -- typed state graph
- ``graph.add_node(name, fn)``      -- register a node function
- ``graph.add_edge(a, b)``          -- unconditional edge
- ``graph.add_conditional_edges(src, fn, mapping)`` -- routing
- ``graph.set_entry_point(name)``   -- equivalent to START -> node
- ``graph.set_finish_point(name)``  -- equivalent to node -> END
- ``graph.compile()``               -- returns a CompiledGraph
- ``compiled.get_graph().draw_mermaid()`` -- acceptance criterion

Parallel execution
-------------------
The 4 research agents run in parallel using LangGraph's fan-out
pattern: the Planner node returns ``[Send(node, state), ...]`` to
dispatch all four simultaneously.  In the skeleton (T-030) we model
this with conditional edges fanning out to all four research nodes
that each connect back to the contrarian node, which LangGraph
executes only once all four have completed (implicit join).

Note on parallel fan-out in LangGraph 0.2.x
---------------------------------------------
True parallel dispatch uses the Send API inside a conditional edge
function.  However, the Send API requires the graph to be compiled
with a checkpointer and the node to be an async node for true
parallelism.  For the skeleton we model fan-out as four sequential
edges from the planner's PROCEED branch to each research node -- the
Mermaid diagram shows the correct topology and the structure is
correct.  T-032 (parallel execution task) will upgrade this to the
full Send API pattern with async execution.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``# type: ignore`` -- use cast() and explicit annotations.
* ``build_graph()`` is a factory function, not a module-level global,
  so tests can call it multiple times without state leaking between runs.
* ``get_compiled_graph()`` is an lru_cache singleton for production use
  (FastAPI startup, LangSmith tracing). Tests always call ``build_graph()``
  directly to get a fresh instance.

Public API
----------
    from backend.graph.graph import build_graph, get_compiled_graph

    # Production: reuse the compiled singleton
    graph = get_compiled_graph()
    result = graph.invoke(initial_state)

    # Tests / dev: build a fresh graph
    compiled = build_graph()
    mermaid = compiled.get_graph().draw_mermaid()
"""

from functools import lru_cache
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.graph.nodes import (
    NODE_CONTRARIAN,
    NODE_FUNDAMENTAL,
    NODE_MACRO,
    NODE_PLANNER,
    NODE_PORTFOLIO_MANAGER,
    NODE_RISK,
    NODE_SENTIMENT,
    NODE_TECHNICAL,
    NODE_VALUATION,
    contrarian_node,
    fundamental_node,
    macro_node,
    planner_node,
    portfolio_manager_node,
    risk_node,
    sentiment_node,
    technical_node,
    valuation_node,
)
from backend.graph.routing import (
    ROUTE_ABORT,
    ROUTE_DEBATE_AGAIN,
    ROUTE_PROCEED,
    route_after_contrarian,
    route_after_planner,
)
from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal fan-out helper
# ---------------------------------------------------------------------------

# Names of the 4 research agent nodes -- used in the fan-out edge mapping.
_RESEARCH_NODES: list[str] = [
    NODE_FUNDAMENTAL,
    NODE_TECHNICAL,
    NODE_SENTIMENT,
    NODE_MACRO,
]


def _research_fan_out(state: InvestmentState) -> list[str]:
    """
    Conditional edge function that fans out to all 4 research agents.

    Returns a list of node names; LangGraph dispatches to all of them
    concurrently (when run with an async executor).  For the skeleton
    this models the correct topology -- T-032 upgrades to true Send API
    parallelism.

    Args:
        state: Current InvestmentState (passed by LangGraph; not used
               directly -- all four agents always run).

    Returns:
        List of all four research node names.
    """
    # state is intentionally unused in the skeleton; it will be
    # inspected in T-032 to support conditional agent exclusion.
    _ = state
    return list(_RESEARCH_NODES)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """
    Build and compile the AIRP LangGraph StateGraph.

    Creates a fresh StateGraph, registers all 9 nodes (1 planner +
    4 research + 4 advanced), defines all edges and conditional edges,
    then compiles to a runnable Pregel object.

    Call this function once at application startup via
    ``get_compiled_graph()`` (lru_cache singleton) or directly in tests
    for an isolated graph instance.

    Returns:
        A compiled LangGraph CompiledGraph object.  Supports:
          - ``.invoke(state)``                       -- synchronous run
          - ``.ainvoke(state)``                      -- async run
          - ``.get_graph().draw_mermaid()``           -- Mermaid diagram
          - ``.get_graph().draw_mermaid_png()``       -- PNG export

    Raises:
        ValueError: If LangGraph detects unreachable nodes or invalid
                    edges during compilation.
    """
    # -- 1. Initialise the StateGraph with our typed state schema ----------
    workflow: StateGraph = StateGraph(InvestmentState)

    # -- 2. Register all nodes ---------------------------------------------
    # Phase 2 nodes (real implementations)
    workflow.add_node(NODE_PLANNER, planner_node)
    workflow.add_node(NODE_FUNDAMENTAL, fundamental_node)
    workflow.add_node(NODE_TECHNICAL, technical_node)
    workflow.add_node(NODE_SENTIMENT, sentiment_node)
    workflow.add_node(NODE_MACRO, macro_node)

    # Phase 4 stub nodes (real implementations added T-039 to T-042)
    workflow.add_node(NODE_CONTRARIAN, contrarian_node)
    workflow.add_node(NODE_RISK, risk_node)
    workflow.add_node(NODE_VALUATION, valuation_node)
    workflow.add_node(NODE_PORTFOLIO_MANAGER, portfolio_manager_node)

    # -- 3. Entry point: START -> planner ----------------------------------
    workflow.add_edge(START, NODE_PLANNER)

    # -- 4. Conditional edge: planner -> (abort to END | fan-out) ----------
    workflow.add_conditional_edges(
        NODE_PLANNER,
        route_after_planner,
        {
            ROUTE_ABORT: END,
            ROUTE_PROCEED: NODE_FUNDAMENTAL,
        },
    )

    # -- 5. Fan-out to remaining research agents ---------------------------
    # Planner routes to fundamental on PROCEED (above).
    # The other three research agents are reached from planner as well
    # via separate direct edges -- LangGraph triggers them in the same
    # super-step as fundamental when they share the same source node.
    #
    # Implementation note: in LangGraph 0.2.x the canonical way to
    # model "run N nodes in parallel after node X" is to add N edges
    # from X to each of the N nodes.  LangGraph's Pregel runtime
    # executes all outbound edges from a node in the same super-step.
    #
    # The conditional edge above handles PROCEED -> fundamental.
    # We add direct edges for the other three from planner:
    workflow.add_edge(NODE_PLANNER, NODE_TECHNICAL)
    workflow.add_edge(NODE_PLANNER, NODE_SENTIMENT)
    workflow.add_edge(NODE_PLANNER, NODE_MACRO)

    # -- 6. Research agents all flow into the contrarian node --------------
    # LangGraph waits for all inbound edges to a node to complete before
    # executing it -- this is the implicit join / barrier for the 4
    # research agents.
    workflow.add_edge(NODE_FUNDAMENTAL, NODE_CONTRARIAN)
    workflow.add_edge(NODE_TECHNICAL, NODE_CONTRARIAN)
    workflow.add_edge(NODE_SENTIMENT, NODE_CONTRARIAN)
    workflow.add_edge(NODE_MACRO, NODE_CONTRARIAN)

    # -- 7. Conditional edge: contrarian -> (loop | risk) ------------------
    workflow.add_conditional_edges(
        NODE_CONTRARIAN,
        route_after_contrarian,
        {
            ROUTE_DEBATE_AGAIN: NODE_CONTRARIAN,  # debate loop (max 2 rounds)
            ROUTE_PROCEED: NODE_RISK,
        },
    )

    # -- 8. Sequential: risk -> valuation -> portfolio_manager -> END ------
    workflow.add_edge(NODE_RISK, NODE_VALUATION)
    workflow.add_edge(NODE_VALUATION, NODE_PORTFOLIO_MANAGER)
    workflow.add_edge(NODE_PORTFOLIO_MANAGER, END)

    # -- 9. Compile --------------------------------------------------------
    compiled: Any = workflow.compile()
    logger.info(
        "build_graph: AIRP StateGraph compiled successfully " "(%d nodes)",
        len(_RESEARCH_NODES) + 5,  # 4 research + planner + 4 advanced
    )
    return compiled


# ---------------------------------------------------------------------------
# Production singleton -- reused across all FastAPI requests
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_compiled_graph() -> Any:
    """
    Return the compiled AIRP graph as a singleton.

    Uses ``lru_cache(maxsize=1)`` so the graph is compiled exactly once
    per process at the cost of one call to ``build_graph()``.  Subsequent
    calls return the cached instance with zero overhead.

    In tests, call ``build_graph()`` directly instead of this function
    to avoid cache pollution across test runs.

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
]
