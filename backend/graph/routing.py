# backend/graph/routing.py
"""
AIRP -- LangGraph Conditional Edge Functions (T-030 / T-031 / T-032 / T-040)

Conditional edge functions determine which node executes next based
on the current state.  LangGraph calls these on edges that need runtime
branching -- routing to error handling when an agent fails, deciding
whether another debate round is needed, or fanning out to parallel
research agents via the Send API.

T-040 changes (Multi-round debate loop)
----------------------------------------
``MAX_DEBATE_ROUNDS`` is promoted to a module-level constant (previously a
local literal inside ``route_after_contrarian``) so that ``backend.graph.
nodes.debate_loop_node`` and tests can reference the exact same value --
no magic numbers duplicated across files.  ``route_after_contrarian``'s
behaviour is otherwise UNCHANGED from T-032/T-038: it is still the single
source of truth for whether another debate round runs, evaluated AFTER
the new ``debate_loop_node`` has appended the round's transcript entry to
``state["debate_rounds"]``.  This keeps every existing T-032/T-038 routing
test passing unmodified while T-040 adds the missing transcript-building
step in between.

T-032 changes (Implement conditional routing logic)
---------------------------------------------------
Two new routing behaviours are introduced in this task:

1. fetch_financials empty -> error handler
   ``route_after_research`` now checks whether the ``fundamental`` output
   contains an ``error`` key from a failed ``fetch_financials`` call.
   When ``fundamental["error"]`` is non-null the pipeline routes to the
   dedicated ``error_handler`` node instead of proceeding to the contrarian.
   The error handler logs the failure, marks the pipeline as degraded, and
   sends it forward so the rest of the committee can still run on whatever
   partial data is available.

2. sentiment.score < -0.8 -> flag for additional research
   After research completes, if ``sentiment["sentiment_score"] < -0.8``
   the pipeline sets the ``NEEDS_ADDITIONAL_SENTIMENT_RESEARCH`` escalation
   flag in state before proceeding.  The contrarian node and portfolio
   manager both check this flag to apply a more conservative stance.
   Routing itself still proceeds normally (this is a flag, not a fork)
   but the flag is surfaced as a route constant so tests can assert on it.

Routing functions
-----------------
route_after_planner
    After the Planner node: dispatch 4 research agents in parallel via
    Send API (T-031), or abort to END if the Planner detected a fatal
    configuration error.

route_after_research
    After all 4 research agents complete (implicit join):
    - If fundamental["error"] is non-null -> ROUTE_ERROR (T-032)
    - If sentiment["sentiment_score"] < -0.8 -> set escalation flag,
      then proceed to contrarian (T-032)
    - Otherwise -> ROUTE_PROCEED

route_after_contrarian
    After the Contrarian Investor node: decide whether to run another
    debate round (bear_conviction >= 7) or proceed to Risk + Valuation.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.

* Plain ASCII section comments (# ---) -- avoids flake8 E501 from
  Unicode box-drawing chars (rule from T-024 onward).

* route_after_planner returns a list[Send] on the PROCEED path,
  not a plain str.  LangGraph dispatches each Send object concurrently,
  giving true parallel execution of the 4 research agents (T-031).

* On the ABORT path, route_after_planner returns the END sentinel
  string so LangGraph terminates the pipeline immediately.

* ROUTE_* constants are used for routing outcomes that are plain str
  (the abort path and the post-research / post-contrarian paths).
  The parallel fan-out path returns List[Send] directly.

* All routing functions use state.get() with defaults -- they must
  never raise, even on partially-populated state.

* NEGATIVE_SENTIMENT_THRESHOLD is a module-level constant so tests
  and the portfolio manager node can import and compare against the
  same value without magic numbers.

Public API
----------
    from backend.graph.routing import (
        ROUTE_PROCEED,
        ROUTE_ABORT,
        ROUTE_ERROR,
        ROUTE_DEBATE_AGAIN,
        NEGATIVE_SENTIMENT_THRESHOLD,
        ESCALATION_FLAG_NEGATIVE_SENTIMENT,
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

#: Error path -- route to the error_handler node when a critical
#: data fetch fails (e.g. fetch_financials returns empty).
ROUTE_ERROR = "error"

#: Run another debate round (bear_conviction >= 7 threshold).
ROUTE_DEBATE_AGAIN = "debate_again"

#: Maximum number of debate rounds the contrarian/debate_loop pair will run
#: before being forced to proceed to Risk Officer regardless of conviction.
#: T-040 acceptance criterion: "max 2 rounds".  Shared by route_after_contrarian
#: and backend.graph.nodes.debate_loop_node so both enforce the identical cap.
MAX_DEBATE_ROUNDS: int = 2

# ---------------------------------------------------------------------------
# Sentiment escalation constants (T-032)
# ---------------------------------------------------------------------------

#: Sentiment score below this threshold triggers the additional-research
#: escalation flag.  Value: -0.8 (on a -1.0 to +1.0 scale).
#: This matches the acceptance criterion: "sentiment.score < -0.8".
NEGATIVE_SENTIMENT_THRESHOLD: float = -0.8

#: State key written to InvestmentState["risk_flags"] when sentiment is
#: severely negative.  Downstream agents check this flag to apply a
#: more conservative stance.
ESCALATION_FLAG_NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT_REQUIRES_ADDITIONAL_RESEARCH"

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
    Conditional edge after all 4 research agents complete (T-032).

    LangGraph's implicit join barrier ensures this function is only
    called after all four inbound Send dispatches have finished.

    Routing logic (evaluated in order):

    1. Financials empty / error check (T-032):
       If ``fundamental["error"]`` is non-null the fundamental analysis
       failed -- most likely because ``fetch_financials`` returned empty
       data (API limit, bad ticker, or network error).  Route to the
       error_handler node so the failure is logged and the pipeline
       status is updated before any downstream agents run.

       Rationale: the Fundamental Analyst is the primary quantitative
       anchor for the entire analysis.  Running a valuation or portfolio
       decision on top of missing fundamental data produces unreliable
       output.  The error_handler does NOT terminate the pipeline -- it
       sets ``fundamental_degraded=True`` in state and forwards to the
       contrarian so the committee can still produce a cautious memo.

    2. Negative sentiment escalation (T-032):
       If ``sentiment["sentiment_score"] < -0.8`` the news environment
       is severely negative.  This does NOT change the route destination
       (we still proceed to contrarian) but it appends
       ESCALATION_FLAG_NEGATIVE_SENTIMENT to ``state["risk_flags"]``
       so downstream agents know to apply a more conservative stance.

       Note: route_after_research is a pure routing function -- it
       cannot modify state directly.  The escalation flag is written
       by returning ROUTE_ESCALATE_SENTIMENT which the graph maps to a
       thin ``sentiment_escalation_node`` that adds the flag, then
       immediately edges forward to the contrarian.  For skeleton
       simplicity in T-032, we return ROUTE_PROCEED with the flag
       written via a single-purpose node (see graph.py T-032 wiring).

       Implementation note: because LangGraph routing functions are
       pure (they cannot mutate state), the negative-sentiment branch
       routes to a dedicated ``sentiment_escalation_node`` that writes
       the flag to state["risk_flags"] before forwarding to contrarian.
       The ROUTE_ESCALATE_SENTIMENT constant is used for this path.

    3. Default: proceed to contrarian.

    Args:
        state: Current InvestmentState after all research agents ran.

    Returns:
        ROUTE_ERROR if fundamentals failed (T-032 error path).
        ROUTE_ESCALATE_SENTIMENT if sentiment < -0.8 (T-032 escalation).
        ROUTE_PROCEED otherwise.
    """
    # --- 1. Fundamentals error check (T-032) --------------------------------
    fundamental_out: Any = state.get("fundamental")
    if isinstance(fundamental_out, dict):
        fund_error: Any = fundamental_out.get("error")
        if fund_error is not None:
            logger.warning(
                "route_after_research: fundamental agent returned error=%r "
                "-- routing to error_handler (T-032 financials-empty path)",
                fund_error,
            )
            return ROUTE_ERROR

    # --- 2. Negative sentiment escalation check (T-032) --------------------
    sentiment_out: Any = state.get("sentiment")
    if isinstance(sentiment_out, dict):
        raw_score: Any = sentiment_out.get("sentiment_score")
        if isinstance(raw_score, (int, float)):
            score: float = float(raw_score)
            if score < NEGATIVE_SENTIMENT_THRESHOLD:
                logger.warning(
                    "route_after_research: sentiment_score=%.3f < %.1f "
                    "-- routing to sentiment_escalation node (T-032)",
                    score,
                    NEGATIVE_SENTIMENT_THRESHOLD,
                )
                return ROUTE_ESCALATE_SENTIMENT

    # --- 3. Log any non-fundamental errors (warn but proceed) ---------------
    agents_with_errors: list[str] = []
    for field, name in [
        ("technical", "technical_analyst"),
        ("sentiment", "sentiment_analyst"),
        ("macro", "macro_economist"),
    ]:
        agent_out: Any = state.get(field)
        if isinstance(agent_out, dict) and agent_out.get("error"):
            agents_with_errors.append(name)

    if agents_with_errors:
        logger.warning(
            "route_after_research: %d non-fundamental agent(s) returned "
            "errors: %s -- proceeding (non-critical)",
            len(agents_with_errors),
            agents_with_errors,
        )
    else:
        logger.info("route_after_research: all research agents completed cleanly")

    return ROUTE_PROCEED


#: Escalation route: sentiment_score < NEGATIVE_SENTIMENT_THRESHOLD.
#: Routes to the sentiment_escalation_node which writes the escalation
#: flag into state["risk_flags"] before forwarding to contrarian.
ROUTE_ESCALATE_SENTIMENT = "escalate_sentiment"


def route_after_contrarian(state: InvestmentState) -> str:
    """
    Conditional edge after the debate_loop node (T-040; was after
    contrarian_node directly in T-032/T-038).

    Routing logic (unchanged from T-038):
    - ``contrarian["bear_conviction"] >= 7`` AND rounds < MAX_DEBATE_ROUNDS
      -> ROUTE_DEBATE_AGAIN (the Contrarian is strongly contra-consensus)
    - Otherwise -> ROUTE_PROCEED (move to Risk Officer)

    T-040 note: this function's edge in graph.py now fires after
    debate_loop_node (which has already appended the round's transcript
    entry to ``state["debate_rounds"]``), not directly after contrarian_node.
    The decision logic itself is identical to T-038 -- only its position in
    the graph topology changed, which is why every pre-existing
    route_after_contrarian test continues to pass unmodified.

    Args:
        state: Current InvestmentState after debate_loop_node() ran.

    Returns:
        ROUTE_DEBATE_AGAIN or ROUTE_PROCEED string.
    """
    contrarian_out: Any = state.get("contrarian")
    debate_count: int = state.get("debate_round_count", 0)

    if debate_count >= MAX_DEBATE_ROUNDS:
        logger.info(
            "route_after_contrarian: max debate rounds (%d) reached "
            "-- proceeding to risk/valuation",
            MAX_DEBATE_ROUNDS,
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
    "ROUTE_ERROR",
    "ROUTE_DEBATE_AGAIN",
    "ROUTE_ESCALATE_SENTIMENT",
    "MAX_DEBATE_ROUNDS",
    "NEGATIVE_SENTIMENT_THRESHOLD",
    "ESCALATION_FLAG_NEGATIVE_SENTIMENT",
    "route_after_planner",
    "route_after_research",
    "route_after_contrarian",
]