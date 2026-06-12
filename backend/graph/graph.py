# backend/graph/graph.py
"""
AIRP -- LangGraph StateGraph with Parallel Research Execution (T-031)

The AIRP investment analysis pipeline expressed as a LangGraph StateGraph.
T-031 upgrades the T-030 skeleton to use the Send API for true parallel
execution of the 4 research agents.

Pipeline topology
-----------------

  START
    |
  [planner]                    validates state, sets status=running
    |
  route_after_planner()
    |  list[Send]              ABORT -> END
    |
    +-- Send -> [fundamental_analyst]    |
    +-- Send -> [technical_analyst]      | all 4 run concurrently
    +-- Send -> [sentiment_analyst]      | in the same super-step
    +-- Send -> [macro_economist]        |
    |
    (implicit join: contrarian waits for all 4 inbound edges)
    |
  [contrarian_investor]        Phase 4 stub (T-040)
    |
  route_after_contrarian()
    | PROCEED          DEBATE_AGAIN (self-loop, max 2 rounds)
    |
  [risk_officer]               Phase 4 stub (T-039)
    |
  [valuation_agent]            Phase 4 stub (T-041)
    |
  [portfolio_manager]          Phase 4 stub (T-042)
    |
  END

Parallel execution via Send API (T-031)
----------------------------------------
LangGraph's Send API enables true parallel fan-out.

``route_after_planner`` returns ``list[Send]``:

    [
        Send("fundamental_analyst", state_dict),
        Send("technical_analyst",   state_dict),
        Send("sentiment_analyst",   state_dict),
        Send("macro_economist",     state_dict),
    ]

LangGraph's Pregel runtime dispatches all four Sends concurrently in
the same super-step. The ``contrarian_investor`` node has four inbound
edges (one from each research node). LangGraph's implicit join barrier
ensures ``contrarian_investor`` only executes after all four research
nodes have written their outputs back to state.

State merging
-------------
Each research node writes a distinct key:
  fundamental_analyst -> {"fundamental": ...}
  technical_analyst   -> {"technical": ...}
  sentiment_analyst   -> {"sentiment": ...}
  macro_economist     -> {"macro": ...}

Since the keys are non-overlapping, LangGraph merges these partial
dicts into the shared state without conflict. No custom reducer is
needed for the InvestmentState TypedDict.

Timing guarantee
----------------
With true parallel execution the total time for the research phase
approaches max(t_fundamental, t_technical, t_sentiment, t_macro)
rather than their sum. The acceptance criterion is:

    total_time < max(individual_agent_times) + PARALLEL_OVERHEAD_S

where PARALLEL_OVERHEAD_S = 5 seconds (scheduling + merge overhead).

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare type: ignore -- use cast() and explicit annotations.
* ``build_graph()`` is a factory function so tests can call it
  multiple times without state leaking between runs.
* ``get_compiled_graph()`` is an lru_cache singleton for production
  (FastAPI startup, LangSmith tracing). Tests always call
  ``build_graph()`` directly to avoid cache pollution.

Public API
----------
    from backend.graph.graph import (
        build_graph,
        get_compiled_graph,
        PARALLEL_OVERHEAD_S,
    )
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
    ROUTE_DEBATE_AGAIN,
    ROUTE_PROCEED,
    route_after_contrarian,
    route_after_planner,
)
from backend.graph.state import InvestmentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum acceptable overhead (seconds) for parallel scheduling and
#: state merging, above the slowest individual agent runtime.
#: Acceptance criterion: total_time < max(individual_times) + PARALLEL_OVERHEAD_S
PARALLEL_OVERHEAD_S: float = 5.0

#: All 4 research agent node names -- used for logging and test assertions.
RESEARCH_NODE_NAMES: tuple[str, ...] = (
    NODE_FUNDAMENTAL,
    NODE_TECHNICAL,
    NODE_SENTIMENT,
    NODE_MACRO,
)

# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """
    Build and compile the AIRP LangGraph StateGraph.

    Creates a fresh StateGraph, registers all 9 nodes, defines edges
    (including the T-031 Send API parallel fan-out from planner to the
    4 research agents), then compiles to a runnable Pregel object.

    The parallel fan-out is implemented via ``route_after_planner``
    returning ``list[Send]`` -- LangGraph dispatches all four Sends
    concurrently in the same super-step.

    Call this once at application startup via ``get_compiled_graph()``
    (lru_cache singleton), or directly in tests for an isolated instance.

    Returns:
        A compiled LangGraph CompiledGraph object. Supports:
          - ``.invoke(state)``                    -- synchronous run
          - ``.ainvoke(state)``                   -- async run
          - ``.get_graph().draw_mermaid()``        -- Mermaid diagram
          - ``.get_graph().draw_mermaid_png()``    -- PNG export

    Raises:
        ValueError: If LangGraph detects unreachable nodes or invalid
                    edges during compilation.
    """
    # -- 1. Initialise the StateGraph with our typed state schema ---------
    workflow: StateGraph = StateGraph(InvestmentState)

    # -- 2. Register all 9 nodes ------------------------------------------
    # Phase 2: real implementations
    workflow.add_node(NODE_PLANNER, planner_node)
    workflow.add_node(NODE_FUNDAMENTAL, fundamental_node)
    workflow.add_node(NODE_TECHNICAL, technical_node)
    workflow.add_node(NODE_SENTIMENT, sentiment_node)
    workflow.add_node(NODE_MACRO, macro_node)

    # Phase 4: stub nodes (T-039 to T-042 replace these)
    workflow.add_node(NODE_CONTRARIAN, contrarian_node)
    workflow.add_node(NODE_RISK, risk_node)
    workflow.add_node(NODE_VALUATION, valuation_node)
    workflow.add_node(NODE_PORTFOLIO_MANAGER, portfolio_manager_node)

    # -- 3. Entry point: START -> planner ---------------------------------
    workflow.add_edge(START, NODE_PLANNER)

    # -- 4. Conditional edge: planner -> Send fan-out OR END (abort) ------
    #
    # route_after_planner() returns:
    #   - list[Send]  when status != "failed"  (parallel dispatch)
    #   - END string  when status == "failed"  (abort, skip all agents)
    #
    # LangGraph 0.2.28 compile-time validation requires every registered
    # node to have at least one statically declared inbound edge.  Send
    # dispatches are runtime-only and are NOT counted by the validator.
    # The fix: include all Send target node names in the mapping dict so
    # the validator sees them as reachable from the planner conditional
    # edge.  At runtime, when route_after_planner returns list[Send],
    # LangGraph bypasses this mapping entirely and dispatches directly to
    # all four nodes concurrently -- the mapping is only used for
    # str-key returns.  When it returns END (str), the mapping resolves
    # "__end__" -> END for the abort path.
    workflow.add_conditional_edges(
        NODE_PLANNER,
        route_after_planner,
        {
            # Abort path: planner failed -> skip all agents -> END
            "__end__": END,
            # Reachability declarations for Send targets.
            # These keys are never returned as strings by route_after_planner
            # (it returns list[Send] instead), but declaring them here
            # satisfies LangGraph 0.2.28's static validator.
            NODE_FUNDAMENTAL: NODE_FUNDAMENTAL,
            NODE_TECHNICAL: NODE_TECHNICAL,
            NODE_SENTIMENT: NODE_SENTIMENT,
            NODE_MACRO: NODE_MACRO,
        },
    )

    # -- 5. Research agents all flow into the contrarian node (join) ------
    #
    # Each research agent has exactly one outbound edge -> contrarian.
    # LangGraph's Pregel runtime uses incoming edge count as a barrier:
    # contrarian_investor will not execute until all 4 research nodes
    # have completed and pushed their partial state updates.
    workflow.add_edge(NODE_FUNDAMENTAL, NODE_CONTRARIAN)
    workflow.add_edge(NODE_TECHNICAL, NODE_CONTRARIAN)
    workflow.add_edge(NODE_SENTIMENT, NODE_CONTRARIAN)
    workflow.add_edge(NODE_MACRO, NODE_CONTRARIAN)

    # -- 6. Conditional edge after research join: -> contrarian routing ---
    #
    # This edge is added as a conditional edge from the contrarian node
    # itself (for the debate loop). The join from research -> contrarian
    # is already handled by the four direct edges above.
    #
    # After contrarian runs, route to another debate round or to risk.
    workflow.add_conditional_edges(
        NODE_CONTRARIAN,
        route_after_contrarian,
        {
            ROUTE_DEBATE_AGAIN: NODE_CONTRARIAN,
            ROUTE_PROCEED: NODE_RISK,
        },
    )

    # -- 7. Sequential: risk -> valuation -> portfolio_manager -> END -----
    # (route_after_research is available for Phase 4 T-037 join node.)
    workflow.add_edge(NODE_RISK, NODE_VALUATION)
    workflow.add_edge(NODE_VALUATION, NODE_PORTFOLIO_MANAGER)
    workflow.add_edge(NODE_PORTFOLIO_MANAGER, END)

    # -- 9. Compile -------------------------------------------------------
    compiled: Any = workflow.compile()
    logger.info(
        "build_graph: AIRP StateGraph compiled with Send API parallel "
        "fan-out (%d research agents, %d total nodes)",
        len(RESEARCH_NODE_NAMES),
        len(RESEARCH_NODE_NAMES) + 5,
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
    per process. Subsequent calls return the cached instance with zero
    overhead.

    In tests, call ``build_graph()`` directly instead of this function
    to avoid cross-test cache pollution.

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
]
