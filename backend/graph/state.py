# backend/graph/state.py
"""
AIRP -- InvestmentState TypedDict (T-029)

The single shared state object that flows through every node in the
LangGraph StateGraph.  Every agent reads from this dict and writes
its output back into it; no agent-to-agent messaging occurs outside
of this state object.

Design decisions
----------------
* TypedDict, not Pydantic model
  LangGraph's StateGraph expects plain dict-compatible state.  TypedDict
  gives us static type checking without adding runtime Pydantic overhead
  on every graph transition.  Agent outputs (which DO need validation) are
  stored as pre-serialised dicts (via model.model_dump()) so they survive
  JSON round-trips through PostgreSQL state persistence.

* NO ``from __future__ import annotations``
  Breaks Pydantic v2 union resolution in agent output models that import
  this module.  This is an established AIRP rule from T-010 onward.

* Plain ASCII section comments (# ---)
  Unicode box-drawing chars caused repeated flake8 E501 failures in
  T-022/T-023.  All new files from T-024 onward use plain ASCII.

* total=False on InvestmentState
  Almost all fields start as None/empty and are populated progressively
  as nodes execute.  total=False means every field is implicitly Optional
  from TypedDict's perspective -- missing keys do not cause TypeErrors
  when accessing a partially-populated state.

* version field
  An integer monotonic version is included so future state migrations
  can distinguish old state snapshots stored in PostgreSQL from new ones
  without needing a schema change.

* Serialisation contract
  Every dict field that stores an agent output MUST contain only
  JSON-serialisable values (str, int, float, bool, list, dict, None).
  Agents achieve this by calling model.model_dump() before writing to
  state.  The helper function ``state_to_json`` / ``state_from_json``
  in this module round-trips the entire state through JSON to verify
  this contract holds.

JSON round-trip guarantee
-------------------------
All fields in InvestmentState must survive::

    json.loads(json.dumps(state, default=str))

The ``default=str`` fallback converts datetime objects to ISO strings.
Tests verify this guarantee holds for a fully-populated state.

Public API
----------
    from backend.graph.state import (
        InvestmentState,
        make_initial_state,
        state_to_json,
        state_from_json,
    )

Usage inside a LangGraph node
------------------------------
    def run_fundamental_analysis(state: InvestmentState) -> dict[str, object]:
        ...
        return {"fundamental": result.model_dump()}
"""

from datetime import datetime
import json
from typing import Any, Optional

# ---------------------------------------------------------------------------
# DebateRound -- one entry in the debate transcript
# ---------------------------------------------------------------------------


class DebateRound:
    """
    Represents one round of the adversarial debate between agents.

    Stored as plain dicts inside InvestmentState["debate_rounds"] for
    JSON compatibility.  This class documents the expected dict shape;
    the actual storage is dict[str, object].

    Fields (as dict keys)
    ---------------------
    round_number    int          1-based debate round index
    agent_responses dict         agent_name -> response text for this round
    contrarian      str          Contrarian Investor's challenge text
    completed_at    str (ISO)    UTC ISO timestamp when the round completed
    """


# ---------------------------------------------------------------------------
# InvestmentState -- the top-level TypedDict
# ---------------------------------------------------------------------------

# We use a plain TypedDict with total=False so partial state is valid.
# This matches how LangGraph populates state incrementally across nodes.
#
# Import note: TypedDict from typing works correctly with mypy --strict
# and does NOT require ``from __future__ import annotations``.

from typing import TypedDict  # noqa: E402 -- must follow class DebateRound


class InvestmentState(TypedDict, total=False):
    """
    Complete shared state for one AIRP investment analysis pipeline run.

    Lifecycle
    ---------
    1. Created by the Planner node (T-029) with company/ticker/job_id.
    2. Populated by 4 parallel research agents (T-022 to T-025).
    3. Enriched by the debate loop (T-037/T-038).
    4. Finalised by Risk Officer, Valuation Agent, and Portfolio Manager.
    5. Persisted to PostgreSQL after every node completes (T-036).

    Every field is Optional (total=False) because state is built
    incrementally.  Fields that have not yet been populated will be
    absent from the dict -- use state.get("field") with a default.

    Agent output fields (fundamental, technical, etc.) store the result
    of model.model_dump() -- a plain dict ready for JSON serialisation
    and PostgreSQL JSONB storage.
    """

    # -----------------------------------------------------------------------
    # Identity -- set by Planner node before any agent runs
    # -----------------------------------------------------------------------

    #: Unique UUID for this analysis job (FK -> analyses.id in PostgreSQL)
    job_id: str

    #: Human-readable company name (e.g. "Tata Consultancy Services")
    company_name: str

    #: Yahoo Finance ticker with exchange suffix (e.g. "TCS.NS")
    ticker: str

    #: NSE or BSE (e.g. "NSE")
    exchange: str

    #: ISIN code when available (e.g. "INE467B01029")
    isin: Optional[str]

    #: Company sector for macro and valuation context (e.g. "Information Technology")
    sector: Optional[str]

    #: Company industry (e.g. "IT Services & Consulting")
    industry: Optional[str]

    #: Raw user input before ticker resolution (e.g. "TCS" or "Tata Consultancy")
    raw_query: str

    #: UTC ISO timestamp when the analysis was triggered
    requested_at: str

    #: User ID of the requester (Clerk user_id, or "anonymous")
    requested_by: str

    # -----------------------------------------------------------------------
    # State version -- for future migrations
    # -----------------------------------------------------------------------

    #: Monotonic integer version of the state schema.
    #: Current version: 1.  Increment when adding/removing fields.
    version: int

    # -----------------------------------------------------------------------
    # Pipeline status
    # -----------------------------------------------------------------------

    #: Overall pipeline status: "pending", "running", "completed", "failed"
    status: str

    #: Which node is currently executing (used for WebSocket progress events)
    current_node: Optional[str]

    #: UTC ISO timestamp when the pipeline started executing
    started_at: Optional[str]

    #: UTC ISO timestamp when the pipeline completed (success or failure)
    completed_at: Optional[str]

    #: Top-level error message if the pipeline failed catastrophically
    pipeline_error: Optional[str]

    # -----------------------------------------------------------------------
    # Research agent outputs -- set after parallel Phase 1 execution
    # Each is a model.model_dump() dict (JSON-serialisable).
    # Absent (not None) until the corresponding agent has run.
    # -----------------------------------------------------------------------

    #: FundamentalAnalysis.model_dump() from the Fundamental Analyst agent
    fundamental: Optional[dict[str, Any]]

    #: TechnicalAnalysis.model_dump() from the Technical Analyst agent
    technical: Optional[dict[str, Any]]

    #: SentimentAnalysis.model_dump() from the News Sentiment agent
    sentiment: Optional[dict[str, Any]]

    #: MacroAnalysis.model_dump() from the Macro Economist agent
    macro: Optional[dict[str, Any]]

    # -----------------------------------------------------------------------
    # Debate transcript -- populated by the debate loop (T-037)
    # -----------------------------------------------------------------------

    #: Number of debate rounds that have been completed
    debate_round_count: int

    #: Full debate transcript -- list of dicts matching the DebateRound shape
    #: Each dict has keys: round_number, agent_responses, contrarian, completed_at
    debate_rounds: list[dict[str, Any]]

    # -----------------------------------------------------------------------
    # Advanced agent outputs -- set after the debate loop
    # -----------------------------------------------------------------------

    #: RiskAnalysis.model_dump() from the Risk Officer agent
    risk: Optional[dict[str, Any]]

    #: ContrarianReport.model_dump() from the Contrarian Investor agent
    contrarian: Optional[dict[str, Any]]

    #: ValuationOutput.model_dump() from the Valuation Agent
    valuation: Optional[dict[str, Any]]

    #: InvestmentDecision.model_dump() from the Portfolio Manager agent
    decision: Optional[dict[str, Any]]

    # -----------------------------------------------------------------------
    # Risk flags -- aggregated across all agents for fast access
    # -----------------------------------------------------------------------

    #: Flat list of all risk flags raised by any agent during the analysis.
    #: Populated by the Risk Officer node after reviewing all prior outputs.
    risk_flags: list[str]

    #: Critical flags (subset of risk_flags) that must be addressed in the memo
    critical_flags: list[str]

    # -----------------------------------------------------------------------
    # Final outputs -- set by Portfolio Manager and Report Generator
    # -----------------------------------------------------------------------

    #: Final verdict: "BUY", "HOLD", or "SELL"
    final_verdict: Optional[str]

    #: Conviction score 1-10 from Portfolio Manager
    conviction_score: Optional[int]

    #: Price target string (e.g. "Rs 4,200 (12-month)"), None if inconclusive
    price_target: Optional[str]

    #: Full Investment Memo as a Markdown string (before PDF conversion)
    memo_markdown: Optional[str]

    #: Path or URL to the generated PDF memo (set by Report Generator node)
    memo_pdf_path: Optional[str]

    # -----------------------------------------------------------------------
    # Document upload context -- set if user uploaded a PDF (annual report etc.)
    # -----------------------------------------------------------------------

    #: ChromaDB collection name where the uploaded document was ingested
    uploaded_doc_collection: Optional[str]

    #: Original filename of the uploaded document
    uploaded_doc_filename: Optional[str]

    #: Number of chunks ingested from the uploaded document
    uploaded_doc_chunk_count: Optional[int]

    # -----------------------------------------------------------------------
    # LangSmith observability -- populated automatically by traced_agent
    # -----------------------------------------------------------------------

    #: LangSmith run IDs for each agent, keyed by agent_name.
    #: Used to construct links to individual agent traces in the dashboard.
    langsmith_run_ids: dict[str, str]


# ---------------------------------------------------------------------------
# Factory -- create a minimal valid initial state
# ---------------------------------------------------------------------------


def make_initial_state(
    job_id: str,
    company_name: str,
    ticker: str,
    exchange: str,
    raw_query: str,
    requested_by: str = "anonymous",
    isin: Optional[str] = None,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> InvestmentState:
    """
    Create a minimal valid InvestmentState for a new analysis job.

    Sets all required identity/metadata fields and initialises list/dict
    fields to empty containers.  Every Optional field is left absent so
    that ``state.get("field")`` returns None naturally.

    Args:
        job_id:        UUID of the analysis job (from PostgreSQL insert).
        company_name:  Human-readable company name.
        ticker:        Yahoo Finance ticker with exchange suffix.
        exchange:      "NSE" or "BSE".
        raw_query:     Raw user input before ticker resolution.
        requested_by:  Clerk user_id of the requester, default "anonymous".
        isin:          Optional ISIN code.
        sector:        Optional sector string.
        industry:      Optional industry string.

    Returns:
        A partially-populated InvestmentState dict ready for the Planner
        node to validate and pass to the LangGraph graph.
    """
    now_iso: str = datetime.utcnow().isoformat() + "Z"

    state: InvestmentState = {
        # Identity
        "job_id": job_id,
        "company_name": company_name,
        "ticker": ticker,
        "exchange": exchange,
        "raw_query": raw_query,
        "requested_at": now_iso,
        "requested_by": requested_by,
        # Schema version
        "version": 1,
        # Pipeline status
        "status": "pending",
        # Lists and dicts -- always initialised to empty containers
        "debate_round_count": 0,
        "debate_rounds": [],
        "risk_flags": [],
        "critical_flags": [],
        "langsmith_run_ids": {},
    }

    # Optional identity fields -- only set if provided
    if isin is not None:
        state["isin"] = isin
    if sector is not None:
        state["sector"] = sector
    if industry is not None:
        state["industry"] = industry

    return state


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def state_to_json(state: InvestmentState) -> str:
    """
    Serialise an InvestmentState to a JSON string.

    Uses ``default=str`` to convert datetime objects (which can appear in
    agent output dicts) to ISO strings.  The resulting string is safe to
    store in PostgreSQL JSONB or pass over a WebSocket connection.

    Args:
        state: Any fully or partially populated InvestmentState dict.

    Returns:
        A JSON string representation of the state.

    Raises:
        TypeError: If any field contains a non-serialisable object that
                   ``default=str`` cannot handle.
    """
    return json.dumps(dict(state), default=str, ensure_ascii=False)


def state_from_json(json_str: str) -> InvestmentState:
    """
    Deserialise an InvestmentState from a JSON string.

    This is the inverse of ``state_to_json``.  Note that datetime objects
    serialised by ``default=str`` are NOT automatically converted back to
    datetime -- they remain as ISO strings.  This is intentional: the state
    stores timestamps as strings throughout.

    Args:
        json_str: A JSON string previously produced by ``state_to_json``.

    Returns:
        An InvestmentState dict.  Type narrowing is performed by cast()
        since JSON deserialisation cannot prove the TypedDict shape at
        runtime; mypy accepts this via the cast.

    Raises:
        json.JSONDecodeError: If the input string is not valid JSON.
    """
    from typing import cast as typing_cast

    raw: Any = json.loads(json_str)
    assert isinstance(raw, dict), "state_from_json: expected a JSON object"
    return typing_cast(InvestmentState, raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "InvestmentState",
    "DebateRound",
    "make_initial_state",
    "state_to_json",
    "state_from_json",
]
