# backend/services/analysis.py
"""
AIRP -- Analysis Trigger & Status Service (T-047 / T-048)

Business logic backing POST /api/v1/analysis/start (T-047) and
GET /api/v1/analysis/{job_id}/status (T-048). Pure service-layer code
with no FastAPI imports (mirrors backend/services/auth.py) so it stays
independently testable without spinning up an ASGI app; each router
translates this module's plain return values and exceptions into the
correct HTTP response shape and status code.

What this module does
----------------------
1. ``resolve_company`` -- turns whatever the caller typed
   (a bare ticker, a company name, or an explicit ticker/exchange
   override) into a canonical (company_name, ticker, exchange) triple.
   Uses the same deterministic "name -> bare symbol" lookup table
   pattern already established in
   backend.agents.valuation_agent._SLUG_OVERRIDES /
   backend.tools.earnings_transcript -- this is intentionally NOT a
   general-purpose NLP ticker resolver (that gap is tracked separately;
   T-047's acceptance criteria only require *an* analysis record to be
   created and the pipeline to start, not perfect ticker resolution for
   arbitrary free text).
2. ``get_or_create_company`` -- looks up the (ticker, exchange) pair in
   the ``companies`` table (T-016 schema) and inserts a new row on first
   use, so repeat analyses of the same company reuse one Company row
   instead of re-resolving and re-inserting every time.
3. ``create_analysis_job`` -- inserts the ``analyses`` row with
   status='pending', the FK to the resolved Company, and the FK to the
   requesting User. Returns the new job's UUID immediately -- this is
   the only database work on the request's synchronous path, which is
   what keeps the endpoint comfortably under the <200ms acceptance
   criterion.
4. ``run_analysis_pipeline`` -- the background-task entry point.
   Builds the initial InvestmentState (backend.graph.state) and invokes
   the compiled LangGraph graph (backend.graph.graph.get_compiled_graph)
   in a worker thread via asyncio.to_thread, so the blocking,
   potentially 60-90 second graph execution never ties up the event
   loop FastAPI uses to serve other requests. On any exception escaping
   the graph (a bug in a node that profile_node's own try/except did not
   already catch, or get_compiled_graph() failing to compile) the
   analysis row is marked status='failed' with the error message --
   the background task itself never raises back into FastAPI's
   BackgroundTasks runner, since an unhandled exception there is only
   logged, not surfaced to any caller.
5. ``compute_progress`` -- pure function: given ``last_completed_node``
   (the column backend.services.state_persistence.StatePersistenceService
   writes after every node, T-033) and the row's ``status``, derives
   ``current_phase``, ``completed_nodes``, and a 0-100
   ``progress_percent`` against CANONICAL_NODE_SEQUENCE -- the same
   15-node topology backend.graph.graph.build_graph wires up (T-031
   through T-043). No I/O; trivially unit-testable.
6. ``get_analysis_status`` -- reads the single ``analyses`` row for a
   job_id (raw SQL, same approach as state_persistence.py, since
   last_completed_node and state_snapshot are not ORM-mapped columns)
   and returns None when the row does not exist OR belongs to a
   different user -- the router (backend/routers/analysis.py) turns
   that None into a 404, deliberately not distinguishing "job does not
   exist" from "job exists but is not yours" so job_id existence is
   never leaked to a non-owner.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- established AIRP rule
  (breaks Pydantic v2 union resolution for modules that import this one).
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* Every database operation is async (SQLAlchemy 2.x asyncpg), matching
  backend.services.auth and backend.services.state_persistence.
* run_analysis_pipeline never raises -- mirrors the "agent/node
  functions must never raise" project rule, extended to the background
  task that drives them.
* get_analysis_status uses raw SQL (sqlalchemy.text), not the ORM, for
  the same reason backend.services.state_persistence does:
  last_completed_node and state_snapshot are columns added by the T-033
  migration directly, never added to the Analysis ORM model (the ORM
  model only maps the original T-016 schema columns).

Public API
----------
    from backend.services.analysis import (
        TickerResolution,
        resolve_company,
        get_or_create_company,
        create_analysis_job,
        run_analysis_pipeline,
        AnalysisStatusResult,
        CANONICAL_NODE_SEQUENCE,
        compute_progress,
        get_analysis_status,
    )
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Optional, cast
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.state import InvestmentState, make_initial_state
from backend.models.orm import Analysis, Company

logger = logging.getLogger(__name__)

__all__ = [
    "TickerResolution",
    "resolve_company",
    "get_or_create_company",
    "create_analysis_job",
    "run_analysis_pipeline",
    "AnalysisStatusResult",
    "CANONICAL_NODE_SEQUENCE",
    "PHASE_DISPLAY_NAMES",
    "compute_progress",
    "get_analysis_status",
]

# ---------------------------------------------------------------------------
# Ticker resolution -- deterministic lookup, NOT a general NLP resolver
# ---------------------------------------------------------------------------

#: Known company name -> bare NSE symbol overrides. Same data and same
#: "same logic as earnings_transcript.py" pattern already used by
#: backend.agents.valuation_agent._SLUG_OVERRIDES, duplicated here
#: (rather than imported) because the agents package and the services
#: package are independent layers -- a router-facing service should not
#: reach into agent-internal helpers, and the table is small enough that
#: keeping two copies in sync is far cheaper than introducing a shared
#: dependency between unrelated layers for a handful of strings.
_COMPANY_NAME_OVERRIDES: dict[str, str] = {
    "tata consultancy services": "TCS",
    "infosys": "INFY",
    "infosys limited": "INFY",
    "reliance industries": "RELIANCE",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "state bank of india": "SBIN",
    "wipro": "WIPRO",
    "hcl technologies": "HCLTECH",
    "tech mahindra": "TECHM",
    "larsen & toubro": "LT",
    "bajaj finance": "BAJFINANCE",
    "asian paints": "ASIANPAINT",
    "itc": "ITC",
    "kotak mahindra bank": "KOTAKBANK",
}

#: Yahoo Finance exchange suffixes keyed by AIRP's exchange code.
_EXCHANGE_SUFFIX: dict[str, str] = {"NSE": ".NS", "BSE": ".BO"}

#: Default exchange when the caller does not specify one.
_DEFAULT_EXCHANGE = "NSE"


@dataclass(frozen=True)
class TickerResolution:
    """
    Canonical (company_name, ticker, exchange) triple produced by
    ``resolve_company``.

    ``ticker`` always carries the Yahoo Finance exchange suffix (e.g.
    'TCS.NS') -- the exact shape backend.graph.state.make_initial_state
    and every research agent's tool calls expect.
    """

    company_name: str
    ticker: str
    exchange: str


def resolve_company(
    raw_query: str,
    ticker_override: Optional[str] = None,
    exchange_override: Optional[str] = None,
) -> TickerResolution:
    """
    Resolve free-text company input into a canonical ticker triple.

    Resolution order:
      1. If ``ticker_override`` is supplied, use it directly (with
         ``exchange_override`` or the default exchange) -- the caller
         already knows the exact Yahoo Finance symbol.
      2. If ``raw_query`` itself already looks like a Yahoo Finance
         ticker (contains a '.' suffix matching a known exchange), use
         it as-is.
      3. Otherwise look up ``raw_query`` (case-insensitive) in
         ``_COMPANY_NAME_OVERRIDES``.
      4. Final fallback: treat ``raw_query`` as a bare ticker symbol
         (upper-cased, whitespace stripped) and append the default
         exchange's suffix. This keeps the endpoint usable for any
         valid NSE symbol even when it is not in the override table,
         consistent with backend.agents.valuation_agent's "strip the
         exchange suffix" fallback behaviour for the reverse direction.

    Args:
        raw_query:         Whatever the caller typed as company_name,
                            e.g. 'TCS', 'Tata Consultancy Services', or
                            'TCS.NS'.
        ticker_override:   Optional explicit Yahoo Finance ticker from
                            AnalysisStartRequest.ticker.
        exchange_override: Optional explicit exchange from
                            AnalysisStartRequest.exchange.

    Returns:
        A TickerResolution with company_name (display name as typed,
        title-cased when it came from the override table), ticker
        (with exchange suffix), and exchange ('NSE' or 'BSE').
    """
    exchange = (exchange_override or _DEFAULT_EXCHANGE).strip().upper()
    if exchange not in _EXCHANGE_SUFFIX:
        exchange = _DEFAULT_EXCHANGE
    suffix = _EXCHANGE_SUFFIX[exchange]

    if ticker_override:
        bare = ticker_override.split(".")[0].strip().upper()
        return TickerResolution(
            company_name=raw_query.strip(),
            ticker=f"{bare}{suffix}",
            exchange=exchange,
        )

    stripped_query = raw_query.strip()
    if "." in stripped_query:
        candidate_suffix = "." + stripped_query.rsplit(".", 1)[-1].upper()
        for exch, sfx in _EXCHANGE_SUFFIX.items():
            if candidate_suffix == sfx:
                bare = stripped_query.rsplit(".", 1)[0].upper()
                return TickerResolution(
                    company_name=raw_query.strip(),
                    ticker=f"{bare}{sfx}",
                    exchange=exch,
                )

    lookup_key = stripped_query.lower()
    if lookup_key in _COMPANY_NAME_OVERRIDES:
        bare = _COMPANY_NAME_OVERRIDES[lookup_key]
        return TickerResolution(
            company_name=raw_query.strip(),
            ticker=f"{bare}{suffix}",
            exchange=exchange,
        )

    bare = stripped_query.upper().replace(" ", "")
    return TickerResolution(
        company_name=raw_query.strip(),
        ticker=f"{bare}{suffix}",
        exchange=exchange,
    )


# ---------------------------------------------------------------------------
# Company persistence
# ---------------------------------------------------------------------------


async def get_or_create_company(
    session: AsyncSession,
    resolution: TickerResolution,
) -> Company:
    """
    Look up the (ticker, exchange) pair in ``companies``; insert on miss.

    Mirrors the find-or-create pattern already used for ``User`` in
    backend.routers.auth.register, but without the IntegrityError race
    handling that endpoint needs -- two concurrent first-time analyses
    of the same brand-new company is an acceptable, vanishingly rare
    edge case for a portfolio project, unlike duplicate user signups
    which are common and security-relevant.

    Args:
        session:    Active AsyncSession for this request.
        resolution: Canonical ticker triple from resolve_company.

    Returns:
        The existing or newly-created Company ORM instance.
    """
    bare_ticker = resolution.ticker.split(".")[0]
    existing = await session.execute(
        select(Company).where(
            Company.ticker == bare_ticker,
            Company.exchange == resolution.exchange,
        )
    )
    company = existing.scalar_one_or_none()
    if company is not None:
        return company

    company = Company(
        name=resolution.company_name,
        ticker=bare_ticker,
        ticker_yf=resolution.ticker,
        exchange=resolution.exchange,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    logger.info(
        "get_or_create_company: created new company ticker=%s exchange=%s",
        bare_ticker,
        resolution.exchange,
    )
    return company


# ---------------------------------------------------------------------------
# Analysis job persistence
# ---------------------------------------------------------------------------


async def create_analysis_job(
    session: AsyncSession,
    company: Company,
    user_id: uuid.UUID,
) -> Analysis:
    """
    Insert a new ``analyses`` row with status='pending'.

    This is the only write on POST /api/v1/analysis/start's synchronous
    path -- a single INSERT plus the get_or_create_company lookup above
    -- which is what keeps the endpoint within the <200ms acceptance
    criterion. The LangGraph pipeline itself (60-90 seconds) is started
    afterward, in the background, by run_analysis_pipeline.

    Args:
        session:    Active AsyncSession for this request.
        company:    The resolved Company row (from get_or_create_company).
        user_id:    UUID of the authenticated requester.

    Returns:
        The newly-created Analysis ORM instance with its server-generated
        UUID populated.
    """
    analysis = Analysis(
        company_id=company.id,
        user_id=user_id,
        status="pending",
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    logger.info(
        "create_analysis_job: created analysis job_id=%s ticker=%s",
        analysis.id,
        company.ticker_yf,
    )
    return analysis


# ---------------------------------------------------------------------------
# Background pipeline execution
# ---------------------------------------------------------------------------


def _invoke_graph_sync(state: InvestmentState) -> InvestmentState:
    """
    Run the compiled LangGraph graph to completion (blocking call).

    Imports backend.graph.graph lazily, inside this function, rather
    than at module level. LangGraph and every one of the 8 agent modules
    it transitively imports are heavy, optional-at-import-time
    dependencies for this service module -- unit tests for
    resolve_company / get_or_create_company / create_analysis_job
    should not need a working LangGraph installation merely because
    they imported backend.services.analysis. This is the same
    "lazy import to keep the test surface narrow" pattern
    backend.graph.nodes._run_persist already uses for
    backend.services.state_persistence.

    Args:
        state: Initial InvestmentState built by run_analysis_pipeline.

    Returns:
        The final InvestmentState after the graph reaches END.
    """
    from backend.graph.graph import get_compiled_graph

    compiled = get_compiled_graph()
    result = compiled.invoke(state)
    return cast(InvestmentState, result)


async def run_analysis_pipeline(
    job_id: uuid.UUID,
    company_name: str,
    ticker: str,
    exchange: str,
    requested_by: str,
) -> None:
    """
    Background-task entry point: build initial state and run the graph.

    Scheduled via FastAPI's BackgroundTasks from the analysis router
    immediately after the response is constructed, so it executes after
    the HTTP response has already been sent to the caller. The actual
    graph invocation is dispatched to a worker thread with
    asyncio.to_thread -- LangGraph nodes are synchronous (T-029 design
    decision; see backend.graph.nodes module docstring) and the full
    pipeline takes up to ~90 seconds, so running it inline on this
    coroutine would block the single event loop FastAPI uses for every
    other concurrent request.

    Never raises: any exception from graph compilation or execution is
    caught, logged, and persisted onto the analyses row as a failure --
    mirroring the project-wide "agent/node functions must never raise"
    rule, extended to the task that drives them. FastAPI's
    BackgroundTasks runner only logs an unhandled exception here; it
    does not retry or notify any caller, so swallowing it explicitly
    (after recording the failure in PostgreSQL, which the dashboard can
    actually surface) is strictly better than letting it propagate
    silently.

    Args:
        job_id:        UUID of the analyses row created by
                        create_analysis_job.
        company_name:  Resolved company display name.
        ticker:        Resolved Yahoo Finance ticker (e.g. 'TCS.NS').
        exchange:      Resolved exchange ('NSE' or 'BSE').
        requested_by:  String identifier of the requesting user
                        (str(user.id)).
    """
    from backend.services.state_persistence import StatePersistenceService

    initial_state = make_initial_state(
        job_id=str(job_id),
        company_name=company_name,
        ticker=ticker,
        exchange=exchange,
        raw_query=company_name,
        requested_by=requested_by,
    )

    logger.info(
        "run_analysis_pipeline: starting background pipeline job_id=%s " "ticker=%s",
        job_id,
        ticker,
    )

    try:
        await asyncio.to_thread(_invoke_graph_sync, initial_state)
        logger.info(
            "run_analysis_pipeline: pipeline completed job_id=%s",
            job_id,
        )
    except Exception as exc:
        logger.error(
            "run_analysis_pipeline: pipeline failed job_id=%s: %s",
            job_id,
            exc,
        )
        from backend.db.session import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as session:
                svc = StatePersistenceService(session)
                await svc.mark_failed(
                    job_id=str(job_id),
                    error_message=str(exc),
                    node_name="run_analysis_pipeline",
                )
        except Exception as persist_exc:
            # Persistence failures here are non-fatal by the same
            # project-wide rule backend.services.state_persistence
            # itself follows -- a DB error while reporting an earlier
            # DB or pipeline error must not crash the background task.
            logger.error(
                "run_analysis_pipeline: failed to mark job_id=%s as " "failed: %s",
                job_id,
                persist_exc,
            )


# ---------------------------------------------------------------------------
# Progress computation (T-048) -- pure function, no I/O
# ---------------------------------------------------------------------------

#: The canonical "happy path" through the 15-node graph
#: (backend.graph.graph.build_graph), used to compute progress percentage.
#: The 4 parallel research agents collapse into one "research" phase here
#: -- from the caller's point of view they start and finish together, and
#: state_persistence.py does not even persist a checkpoint for them
#: individually (only research_join_node, which runs after all 4 join, is
#: wrapped with _persist_after). error_handler and sentiment_escalation
#: are intentionally excluded: they are conditional detours that do not
#: run on every analysis (backend.graph.routing.route_after_research), so
#: including them in the denominator would understate progress for the
#: (much more common) path that skips them.
CANONICAL_NODE_SEQUENCE: tuple[str, ...] = (
    "planner",
    "research_join",
    "contrarian_investor",
    "debate_loop",
    "risk_officer",
    "valuation_agent",
    "portfolio_manager",
    "report_generator",
    "pdf_export",
)

#: Human-readable label for each canonical phase, shown as
#: AnalysisStatusResponse.current_phase. Falls back to the raw node name
#: (see compute_progress) for any node not in this table -- e.g.
#: error_handler or sentiment_escalation, which can appear in
#: last_completed_node on the (uncommon) detour paths even though they
#: are not part of CANONICAL_NODE_SEQUENCE.
PHASE_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Resolving company and initialising analysis",
    "research_join": "Running fundamental, technical, sentiment, and macro research",
    "error_handler": "Recovering from a research data error",
    "sentiment_escalation": "Flagging severe negative sentiment for review",
    "contrarian_investor": "Building the bear case",
    "debate_loop": "Running agent debate round",
    "risk_officer": "Assessing governance and regulatory risk",
    "valuation_agent": "Running DCF valuation and peer comparison",
    "portfolio_manager": "Synthesising the final investment decision",
    "report_generator": "Writing the Investment Memo",
    "pdf_export": "Exporting the Investment Memo PDF",
}

#: Phase label shown before the planner node has completed -- there is
#: no last_completed_node yet, only status='pending'.
_PHASE_NOT_STARTED = "Queued -- waiting for the pipeline to start"

#: Phase label shown once status='completed', regardless of which node
#: technically wrote the last checkpoint (T-029/T-043 set
#: status='completed' as early as portfolio_manager_node, since
#: report_generator and pdf_export are best-effort finishing touches --
#: see backend.graph.nodes._portfolio_manager_impl).
_PHASE_COMPLETED = "Analysis complete"

#: Phase label shown when status='failed' but last_completed_node is
#: still NULL -- the pipeline failed before the planner's first
#: checkpoint even persisted (e.g. get_compiled_graph() itself raised
#: during compilation, inside run_analysis_pipeline's except block).
_PHASE_FAILED_BEFORE_START = "Failed before the pipeline could start"

#: Phase label prefix shown when status='failed' AND last_completed_node
#: names a real checkpoint -- last_completed_node still names whichever
#: node persisted the last good checkpoint BEFORE the failure
#: (mark_failed does not change last_completed_node), so showing that
#: node's normal in-progress phrasing on its own would misleadingly read
#: as "still running". This prefixes it instead.
_PHASE_FAILED_PREFIX = "Failed after: "


@dataclass(frozen=True)
class AnalysisStatusResult:
    """
    Everything GET /api/v1/analysis/{job_id}/status needs, already
    derived. Built by ``get_analysis_status``; the router maps this
    1:1 onto ``backend.models.schemas.AnalysisStatusResponse``.
    """

    job_id: uuid.UUID
    status: str
    current_phase: str
    completed_nodes: list[str]
    progress_percent: int
    error_message: Optional[str]
    requested_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


def compute_progress(
    last_completed_node: Optional[str],
    status: str,
) -> tuple[str, list[str], int]:
    """
    Derive (current_phase, completed_nodes, progress_percent) from the
    raw ``last_completed_node`` / ``status`` columns on an ``analyses``
    row. Pure function -- no I/O, trivially unit-testable.

    Semantics of last_completed_node (set by
    backend.graph.nodes._persist_after, T-033): it names the node that
    JUST finished, not the one currently running. So
    last_completed_node='planner' means the 4 research agents are
    starting/running next; completed_nodes therefore includes every
    CANONICAL_NODE_SEQUENCE entry up to AND INCLUDING the matched node,
    and current_phase describes that same just-completed node (there is
    no separate "next node" name to show until IT completes and persists
    its own checkpoint).

    When status == 'failed', current_phase is prefixed with "Failed
    after: " (or, if no checkpoint exists yet, replaced entirely with
    "Failed before the pipeline could start") rather than reusing the
    plain in-progress phrasing -- mark_failed (T-033) does not change
    last_completed_node, so without this the response would otherwise
    describe a failed job as if a phase were still actively running.

    Args:
        last_completed_node: The analyses.last_completed_node column
            value (None until the planner node's first checkpoint).
        status: The analyses.status column value -- 'pending',
            'running', 'completed', or 'failed'.

    Returns:
        A 3-tuple:
          current_phase:     human-readable phase description
          completed_nodes:   CANONICAL_NODE_SEQUENCE prefix reached so far
          progress_percent:  0-100, 100 only when status == 'completed'
    """
    if status == "completed":
        return (_PHASE_COMPLETED, list(CANONICAL_NODE_SEQUENCE), 100)

    if not last_completed_node:
        if status == "failed":
            return (_PHASE_FAILED_BEFORE_START, [], 0)
        return (_PHASE_NOT_STARTED, [], 0)

    total = len(CANONICAL_NODE_SEQUENCE)
    try:
        position = CANONICAL_NODE_SEQUENCE.index(last_completed_node)
        completed_nodes = list(CANONICAL_NODE_SEQUENCE[: position + 1])
        progress_percent = min(99, round((position + 1) / total * 100))
    except ValueError:
        # last_completed_node is a real node (error_handler,
        # sentiment_escalation, or one of the 4 parallel research
        # agents) that simply is not part of the canonical sequence --
        # report it by name without claiming a specific percentage
        # position, rather than silently treating it as 0% progress.
        completed_nodes = []
        progress_percent = 1

    if status == "failed":
        node_label = PHASE_DISPLAY_NAMES.get(last_completed_node, last_completed_node)
        return (_PHASE_FAILED_PREFIX + node_label, completed_nodes, progress_percent)

    current_phase = PHASE_DISPLAY_NAMES.get(last_completed_node, last_completed_node)
    return (current_phase, completed_nodes, progress_percent)


# ---------------------------------------------------------------------------
# Status read (T-048) -- raw SQL, same approach as state_persistence.py
# ---------------------------------------------------------------------------

#: Reads every column AnalysisStatusResult needs in one round trip.
#: Raw SQL (not the ORM) because last_completed_node and state_snapshot
#: are T-033-migration-only columns, never added to the Analysis ORM
#: model (backend.models.orm.Analysis maps only the original T-016
#: schema) -- the exact same reason state_persistence.py's
#: _SQL_LOAD_SNAPSHOT uses text() instead of select(Analysis).
_SQL_LOAD_STATUS = text(
    """
    SELECT user_id,
           status,
           last_completed_node,
           error_message,
           requested_at,
           started_at,
           completed_at
      FROM analyses
     WHERE id = CAST(:job_id AS uuid)
     LIMIT 1
    """
)


async def get_analysis_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[AnalysisStatusResult]:
    """
    Read the current status of an analysis job, scoped to its owner.

    Returns None both when no ``analyses`` row exists for job_id AND
    when a row exists but belongs to a different user -- deliberately
    not distinguishing the two so the router
    (backend.routers.analysis.get_analysis_status_endpoint) can return
    404 in both cases without ever revealing to a non-owner whether a
    given job_id is valid.

    Args:
        session: Active AsyncSession for this request.
        job_id:  UUID path parameter from the request.
        user_id: UUID of the authenticated requester
                 (current_user.id from get_current_user).

    Returns:
        AnalysisStatusResult when job_id exists and belongs to user_id,
        else None.
    """
    result = await session.execute(_SQL_LOAD_STATUS, {"job_id": str(job_id)})
    row: Any = result.fetchone()

    if row is None:
        logger.debug(
            "get_analysis_status: no analyses row for job_id=%s",
            job_id,
        )
        return None

    row_user_id = row[0]
    if row_user_id is not None and uuid.UUID(str(row_user_id)) != user_id:
        logger.warning(
            "get_analysis_status: job_id=%s belongs to a different user "
            "-- returning not-found to requester",
            job_id,
        )
        return None

    status: str = str(row[1])
    last_completed_node: Optional[str] = row[2]
    current_phase, completed_nodes, progress_percent = compute_progress(
        last_completed_node=last_completed_node,
        status=status,
    )

    return AnalysisStatusResult(
        job_id=job_id,
        status=status,
        current_phase=current_phase,
        completed_nodes=completed_nodes,
        progress_percent=progress_percent,
        error_message=row[3],
        requested_at=row[4],
        started_at=row[5],
        completed_at=row[6],
    )
