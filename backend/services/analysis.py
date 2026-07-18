# backend/services/analysis.py
"""
AIRP -- Analysis Trigger, Status, Result, Charts & History Service
(T-047 / T-048 / T-050 / T-062)

Business logic backing POST /api/v1/analysis/start (T-047),
GET /api/v1/analysis/{job_id}/status (T-048), and (T-050)
GET /api/v1/analysis/{job_id}/result, the PDF-existence check backing
GET /api/v1/analysis/{job_id}/memo/pdf, GET /api/v1/analysis/history,
and (T-062) GET /api/v1/analysis/{job_id}/charts.
Pure service-layer code with no FastAPI imports (mirrors
backend/services/auth.py) so it stays independently testable without
spinning up an ASGI app; each router translates this module's plain
return values and exceptions into the correct HTTP response shape and
status code.

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
7. ``get_analysis_result`` (T-050) -- reads the same ``state_snapshot``
   JSONB column (T-033) and returns its ``decision`` key (an
   InvestmentDecision.model_dump() dict, see
   backend.graph.state.InvestmentState) once the pipeline has reached
   status='completed'. Same None-for-not-found-or-not-yours contract
   as get_analysis_status; raises AnalysisNotReadyError (distinct from
   the None case) when the job is real and owned by the caller but has
   not finished yet, so the router can return 409 instead of 404 for
   that case.
8. ``get_analysis_history`` (T-050) -- paginated list of a user's past
   analyses (newest first), joining ``analyses`` to ``companies`` for
   display name/ticker/exchange and pulling verdict/conviction_score
   out of state_snapshot via Postgres's JSONB ->> operator rather than
   loading and parsing the full snapshot in Python per row.
9. ``get_analysis_chart_data`` (T-062) -- reuses the identical
   ``_SQL_LOAD_RESULT`` query get_analysis_result already issues (same
   three columns: ownership, status, state_snapshot) but reads
   ``ticker``/``valuation``/``sentiment``/``risk`` out of the snapshot
   instead of ``decision``, then makes two LIVE yFinance calls
   (fetch_ohlcv, fetch_income_statement -- both existing T-018/T-019
   tools, each offloaded to a worker thread via asyncio.to_thread) to
   get the 1-year price series and 4-year revenue/profit trend, since
   neither was ever persisted into state_snapshot by the original
   pipeline run (only derived summary statistics were). Each of the
   five chart data sources degrades independently -- a failed live
   fetch or a missing snapshot key produces ``None``/an empty list for
   that one chart plus a warning string, never a 500 for the whole
   endpoint.

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
        AnalysisNotReadyError,
        AnalysisResultData,
        get_analysis_result,
        HistoryEntry,
        HistoryPage,
        get_analysis_history,
        DEFAULT_HISTORY_PAGE_SIZE,
        MAX_HISTORY_PAGE_SIZE,
        AnalysisChartData,
        get_analysis_chart_data,
    )
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any, Optional, cast
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.state import InvestmentState, make_initial_state
from backend.models.orm import Analysis, Company
from backend.tools.financials import fetch_income_statement
from backend.tools.stock_price import fetch_ohlcv

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
    "AnalysisNotReadyError",
    "AnalysisResultData",
    "get_analysis_result",
    "HistoryEntry",
    "HistoryPage",
    "get_analysis_history",
    "DEFAULT_HISTORY_PAGE_SIZE",
    "MAX_HISTORY_PAGE_SIZE",
    "AnalysisChartData",
    "get_analysis_chart_data",
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


# ---------------------------------------------------------------------------
# Result read (T-050) -- full InvestmentDecision JSON
# ---------------------------------------------------------------------------


class AnalysisNotReadyError(Exception):
    """
    Raised by ``get_analysis_result`` when ``job_id`` exists and belongs
    to the caller, but the pipeline has not yet produced a decision --
    ``status`` is 'pending', 'running', or 'failed'.

    Deliberately a distinct exception rather than a third ``None``-like
    sentinel returned alongside the "not found" ``None``: the router
    (backend.routers.analysis.get_analysis_result_endpoint) needs to
    tell these two cases apart to choose between 404 (job_id does not
    exist or is not yours -- same not-found semantics as
    get_analysis_status) and 409 Conflict (job_id is real and yours,
    but there is genuinely no decision yet to return). Carrying
    ``status`` on the exception instance lets the router's error detail
    explain *why* -- "still running" reads very differently from
    "failed" -- without a second database round trip to re-derive it.
    """

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(
            f"Analysis job_id has status={status!r} -- no decision available yet"
        )


@dataclass(frozen=True)
class AnalysisResultData:
    """
    Everything GET /api/v1/analysis/{job_id}/result needs to build an
    ``InvestmentDecisionResponse``. Built by ``get_analysis_result``;
    the router maps ``decision`` 1:1 onto that schema's fields (it is
    already an ``InvestmentDecision.model_dump()`` dict -- see
    backend.graph.state.InvestmentState's ``decision`` field) and uses
    ``company_name``/``ticker`` only as a cross-check that the snapshot
    actually contains a populated decision.

    ``fundamental_years_available`` (T-084) is the one field here that
    is NOT sourced from ``decision`` -- it comes from the same
    ``state_snapshot``'s ``fundamental`` entry instead (the Fundamental
    Analyst's own output), added specifically to power the Investment
    Memo / MemoPage "based on N of 4 years" data-completeness note
    without a second round trip to the database. None when the snapshot
    has no ``fundamental`` entry, or that entry has no usable
    ``years_available`` value.
    """

    job_id: uuid.UUID
    status: str
    decision: dict[str, Any]
    fundamental_years_available: Optional[int] = None


#: Reads the three columns get_analysis_result needs in one round trip:
#: ownership (user_id), lifecycle status (to distinguish "not ready"
#: from "ready"), and the full state snapshot the decision dict lives
#: inside. Raw SQL for the same reason _SQL_LOAD_STATUS is -- state_snapshot
#: is a T-033-migration-only column, never added to the Analysis ORM model.
_SQL_LOAD_RESULT = text(
    """
    SELECT user_id,
           status,
           state_snapshot
      FROM analyses
     WHERE id = CAST(:job_id AS uuid)
     LIMIT 1
    """
)


async def get_analysis_result(
    session: AsyncSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[AnalysisResultData]:
    """
    Read the final InvestmentDecision for a completed analysis job.

    Returns None both when no ``analyses`` row exists for job_id AND
    when a row exists but belongs to a different user -- identical
    not-found semantics to ``get_analysis_status``, for the identical
    reason (never reveal job_id validity to a non-owner). Raises
    ``AnalysisNotReadyError`` when job_id is real and owned by the
    caller but ``status`` is not yet 'completed' -- the router
    translates that into 409, distinct from 404.

    Args:
        session: Active AsyncSession for this request.
        job_id:  UUID path parameter from the request.
        user_id: UUID of the authenticated requester.

    Returns:
        AnalysisResultData when job_id exists, belongs to user_id, and
        status == 'completed'. None when job_id does not exist or
        belongs to a different user.

    Raises:
        AnalysisNotReadyError: job_id exists and belongs to user_id,
            but status is 'pending', 'running', or 'failed'.
    """
    result = await session.execute(_SQL_LOAD_RESULT, {"job_id": str(job_id)})
    row: Any = result.fetchone()

    if row is None:
        logger.debug(
            "get_analysis_result: no analyses row for job_id=%s",
            job_id,
        )
        return None

    row_user_id = row[0]
    if row_user_id is not None and uuid.UUID(str(row_user_id)) != user_id:
        logger.warning(
            "get_analysis_result: job_id=%s belongs to a different user "
            "-- returning not-found to requester",
            job_id,
        )
        return None

    status: str = str(row[1])
    if status != "completed":
        logger.info(
            "get_analysis_result: job_id=%s not ready (status=%s)",
            job_id,
            status,
        )
        raise AnalysisNotReadyError(status=status)

    snapshot_val: Any = row[2]
    decision = _extract_decision_from_snapshot(snapshot_val, job_id=job_id)
    if decision is None:
        # status='completed' but the snapshot has no decision -- should
        # not happen given the graph topology (portfolio_manager_node
        # sets both status='completed' and state["decision"] in the
        # same return dict -- see backend.graph.nodes), but a malformed
        # or partially-written snapshot must surface as "not ready"
        # rather than crash the endpoint with an attribute error deep
        # inside response serialisation.
        logger.error(
            "get_analysis_result: job_id=%s status=completed but no "
            "decision found in state_snapshot -- treating as not ready",
            job_id,
        )
        raise AnalysisNotReadyError(status=status)

    fundamental_years_available = _extract_fundamental_years_available_from_snapshot(
        snapshot_val, job_id=job_id
    )

    return AnalysisResultData(
        job_id=job_id,
        status=status,
        decision=decision,
        fundamental_years_available=fundamental_years_available,
    )


def _parse_state_snapshot(
    snapshot_val: Any,
    job_id: uuid.UUID,
) -> Optional[dict[str, Any]]:
    """
    Normalise ``analyses.state_snapshot`` (JSONB) into a plain dict, or
    None if it is missing or malformed.

    Mirrors backend.services.state_persistence.StatePersistenceService.load's
    own asyncpg-vs-psycopg2 normalisation (asyncpg returns JSONB as a
    dict already; psycopg2 returns a JSON string) -- duplicated here
    rather than imported because that method returns a full
    InvestmentState dict via a private cast this module does not need,
    and both ``_extract_decision_from_snapshot`` (GET /result) and
    ``_extract_chart_inputs_from_snapshot`` (GET /charts, T-062) only
    ever need a handful of top-level keys out of ~30 InvestmentState
    fields -- one shared normalisation step, two different callers
    picking their own keys back out of the same parsed dict.

    Args:
        snapshot_val: The raw value read from row[2] -- a dict
                      (asyncpg) or str (psycopg2), or None.
        job_id:       Only used for logging context.

    Returns:
        The parsed snapshot dict, or None if absent/unparseable.
    """
    if snapshot_val is None:
        return None

    if isinstance(snapshot_val, dict):
        snapshot: Any = snapshot_val
    else:
        try:
            snapshot = json.loads(str(snapshot_val))
        except json.JSONDecodeError as exc:
            logger.error(
                "_parse_state_snapshot: invalid state_snapshot JSON for job_id=%s: %s",
                job_id,
                exc,
            )
            return None

    if not isinstance(snapshot, dict):
        return None
    return snapshot


def _extract_decision_from_snapshot(
    snapshot_val: Any,
    job_id: uuid.UUID,
) -> Optional[dict[str, Any]]:
    """
    Parse ``analyses.state_snapshot`` (JSONB) and return its ``decision``
    key, or None if the snapshot is missing, malformed, or has no
    decision.

    Args:
        snapshot_val: The raw value read from row[2] -- a dict
                      (asyncpg) or str (psycopg2), or None.
        job_id:       Only used for logging context.

    Returns:
        The ``decision`` dict, or None if absent/unparseable.
    """
    snapshot = _parse_state_snapshot(snapshot_val, job_id=job_id)
    if snapshot is None:
        return None

    decision = snapshot.get("decision")
    if not isinstance(decision, dict):
        return None
    return decision


def _extract_fundamental_years_available_from_snapshot(
    snapshot_val: Any,
    job_id: uuid.UUID,
) -> Optional[int]:
    """
    Parse ``analyses.state_snapshot`` (JSONB) and return the Fundamental
    Analyst's ``years_available`` count (T-084), or None if the
    snapshot is missing, malformed, has no ``fundamental`` entry, or
    that entry has no usable ``years_available`` value.

    Soft signal only -- unlike ``_extract_decision_from_snapshot``, a
    None here never raises ``AnalysisNotReadyError``. The memo/MemoPage
    "based on N of 4 years" note simply omits itself when this returns
    None, exactly as it already does when years_available == 4.

    Args:
        snapshot_val: The raw value read from row[2] -- a dict
                      (asyncpg) or str (psycopg2), or None.
        job_id:       Only used for logging context.

    Returns:
        years_available as an int (0-4 in practice), or None if
        unavailable or malformed.
    """
    snapshot = _parse_state_snapshot(snapshot_val, job_id=job_id)
    if snapshot is None:
        return None

    fundamental = snapshot.get("fundamental")
    if not isinstance(fundamental, dict):
        return None

    years_raw = fundamental.get("years_available")
    if years_raw is None:
        return None
    try:
        return int(years_raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# History (T-050) -- paginated list of a user's past analyses
# ---------------------------------------------------------------------------

#: Default and maximum page size for GET /api/v1/analysis/history.
#: The acceptance criterion names "past 20 analyses" as the default
#: view; the router's Query(ge=1, le=MAX_HISTORY_PAGE_SIZE) accepts a
#: smaller explicit limit but never a larger one, so a caller cannot
#: force an unbounded query against the analyses table.
DEFAULT_HISTORY_PAGE_SIZE = 20
MAX_HISTORY_PAGE_SIZE = 100


@dataclass(frozen=True)
class HistoryEntry:
    """One row of GET /api/v1/analysis/history's paginated result."""

    job_id: uuid.UUID
    company_name: str
    ticker: str
    exchange: str
    status: str
    requested_at: datetime
    completed_at: Optional[datetime]
    verdict: Optional[str]
    conviction_score: Optional[int]


@dataclass(frozen=True)
class HistoryPage:
    """
    A single page of ``HistoryEntry`` rows plus enough metadata for the
    caller to request the next page without it having to separately
    track an offset across requests, and to render "page X of Y" /
    disable a "next" control once exhausted.
    """

    items: list[HistoryEntry]
    total_count: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """True when at least one further row exists beyond this page."""
        return self.offset + len(self.items) < self.total_count


#: Joins analyses -> companies to get the display name/ticker/exchange
#: in one round trip, and pulls verdict/conviction_score out of the
#: JSONB state_snapshot via Postgres's ->> operator rather than loading
#: and parsing the full snapshot in Python for every row on the page --
#: a history list only ever needs two scalar fields out of the dict, so
#: letting Postgres extract them avoids ~20 wasted json.loads calls
#: per page for fields the response never uses. ->> 'decision' yields
#: NULL (rather than raising) for any row whose snapshot has no
#: 'decision' key yet (pending/running/failed jobs), which is exactly
#: the fallback HistoryEntry.verdict/conviction_score want for those
#: rows -- Optional[str]/Optional[int] in the dataclass, surfaced as
#: null in the JSON response rather than a fabricated placeholder.
_SQL_LOAD_HISTORY_PAGE = text(
    """
    SELECT a.id,
           c.name,
           c.ticker_yf,
           c.exchange,
           a.status,
           a.requested_at,
           a.completed_at,
           a.state_snapshot -> 'decision' ->> 'verdict'           AS verdict,
           a.state_snapshot -> 'decision' ->> 'conviction_score'  AS conviction_score
      FROM analyses a
      JOIN companies c ON c.id = a.company_id
     WHERE a.user_id = CAST(:user_id AS uuid)
     ORDER BY a.requested_at DESC
     LIMIT :limit OFFSET :offset
    """
)

_SQL_COUNT_HISTORY = text(
    """
    SELECT COUNT(*)
      FROM analyses
     WHERE user_id = CAST(:user_id AS uuid)
    """
)


async def get_analysis_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int = DEFAULT_HISTORY_PAGE_SIZE,
    offset: int = 0,
) -> HistoryPage:
    """
    Read one page of a user's past analyses, newest first.

    Two queries (a COUNT and the page itself) rather than a single
    window-function query -- this endpoint is read by a human dashboard
    at human-interaction frequency, not a hot loop, so the second round
    trip's latency is immaterial next to the clarity of two plain,
    independently-readable SQL statements over one combining
    ``COUNT(*) OVER()`` with the row fetch.

    Args:
        session: Active AsyncSession for this request.
        user_id: UUID of the authenticated requester -- every row
                 returned belongs to this user; there is no
                 cross-user history endpoint.
        limit:   Page size, already clamped to
                 [1, MAX_HISTORY_PAGE_SIZE] by the router's
                 ``Query(ge=1, le=MAX_HISTORY_PAGE_SIZE)`` validation
                 before this function is called.
        offset:  Rows to skip, already clamped to >= 0 by the same
                 validation.

    Returns:
        A HistoryPage with up to ``limit`` HistoryEntry rows and the
        total count of the user's analyses (for pagination metadata),
        regardless of how many fit on this particular page.
    """
    count_result = await session.execute(_SQL_COUNT_HISTORY, {"user_id": str(user_id)})
    total_count = int(count_result.scalar_one())

    page_result = await session.execute(
        _SQL_LOAD_HISTORY_PAGE,
        {"user_id": str(user_id), "limit": limit, "offset": offset},
    )
    rows = page_result.fetchall()

    items = [
        HistoryEntry(
            job_id=row[0],
            company_name=row[1],
            ticker=row[2],
            exchange=row[3],
            status=row[4],
            requested_at=row[5],
            completed_at=row[6],
            verdict=row[7],
            conviction_score=int(row[8]) if row[8] is not None else None,
        )
        for row in rows
    ]

    return HistoryPage(items=items, total_count=total_count, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Chart data (T-062) -- price history, revenue/profit trend, valuation,
# sentiment, and risk data for the frontend charts page
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisChartData:
    """
    Everything GET /api/v1/analysis/{job_id}/charts needs to build an
    AnalysisChartDataResponse. Built by ``get_analysis_chart_data``;
    the router maps each field 1:1 onto that schema.

    ``price_history``/``financials`` come from a LIVE yFinance call
    this function makes (never persisted by the original pipeline
    run -- only derived summary statistics were);
    ``valuation``/``sentiment``/``risk`` come straight out of
    ``state_snapshot``, already computed once during the pipeline and
    never re-fetched. Every field is independently optional/empty-able
    -- see this module's docstring, item 9, for why one missing or
    failed source must not fail the whole response.
    """

    job_id: uuid.UUID
    ticker: str
    company_name: str
    price_currency: str
    price_history: list[dict[str, Any]]
    financials: list[dict[str, Any]]
    valuation: Optional[dict[str, Any]]
    sentiment: Optional[dict[str, Any]]
    risk: Optional[dict[str, Any]]
    data_warnings: list[str]


def _fetch_price_history_sync(
    ticker: str,
) -> tuple[list[dict[str, Any]], str, Optional[str]]:
    """
    Blocking yFinance call (via the existing T-018 ``fetch_ohlcv``
    tool) -- callers MUST run this through ``asyncio.to_thread``, never
    directly on the event loop.

    Nearly always a Redis cache hit in practice: fetch_ohlcv shares its
    cache key (``airp:stock:{ticker}:{period}``, STOCK_TTL) with
    fetch_stock_price, which the Technical Analyst agent already called
    for this exact ticker/period during the original pipeline run.

    Returns:
        (price_points, currency, warning) -- price_points is already
        the exact ``{date, close, volume}`` shape PricePointResponse
        expects, ready to pass straight into that schema. On failure,
        price_points is ``[]`` and warning explains why.
    """
    result = fetch_ohlcv.invoke({"ticker": ticker, "period": "1y"})
    if "error" in result:
        message = result.get("message", result["error"])
        logger.warning(
            "get_analysis_chart_data: fetch_ohlcv failed for ticker=%s: %s",
            ticker,
            message,
        )
        return [], "INR", f"Price history unavailable: {message}"

    price_points = [
        {"date": candle["date"], "close": candle["close"], "volume": candle["volume"]}
        for candle in result.get("ohlcv", [])
    ]
    currency = cast(str, result.get("currency", "INR"))
    return price_points, currency, None


def _fetch_financial_trend_sync(
    ticker: str,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    Blocking yFinance call (via the existing T-019
    ``fetch_income_statement`` tool) -- callers MUST run this through
    ``asyncio.to_thread``.

    Unlike price history, this is NOT Redis-cached (fetch_income_statement
    has no ``@cached`` decorator) -- every call re-hits yFinance, even
    though the Fundamental Analyst already fetched the same statements
    once during the original pipeline run. Tracked as a known gap
    (see docs/week-17/T-062-Build-Charts-And-Visualisations.md), out of
    scope for this task to fix.

    Returns:
        (financial_points, warning) -- financial_points is already the
        exact ``{fiscal_year, revenue_crores, net_income_crores}`` shape
        RevenueProfitPointResponse expects. On failure, financial_points
        is ``[]`` and warning explains why.
    """
    result = fetch_income_statement.invoke({"ticker": ticker})
    if "error" in result:
        message = result.get("message", result["error"])
        logger.warning(
            "get_analysis_chart_data: fetch_income_statement failed for ticker=%s: %s",
            ticker,
            message,
        )
        return [], f"Revenue/profit trend unavailable: {message}"

    financial_points = [
        {
            "fiscal_year": year["fiscal_year"],
            "revenue_crores": year.get("revenue_crores"),
            "net_income_crores": year.get("net_income_crores"),
        }
        for year in result.get("income_statement", [])
    ]
    return financial_points, None


async def get_analysis_chart_data(
    session: AsyncSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[AnalysisChartData]:
    """
    Assemble chart-ready data for a completed analysis job.

    Same None-for-not-found-or-not-yours / ``AnalysisNotReadyError``-
    for-not-finished-yet contract as ``get_analysis_result`` (reuses
    that function's exact ``_SQL_LOAD_RESULT`` query -- both need only
    ownership, status, and state_snapshot) -- the router applies the
    identical 404/409 translation for both endpoints.

    Unlike ``get_analysis_result``, a missing or failed individual
    chart source here never raises: it degrades to an empty list/None
    for that one field plus an entry in ``data_warnings``, so one
    failed live yFinance call cannot take down the four other charts.

    Args:
        session: Active AsyncSession for this request.
        job_id:  UUID path parameter from the request.
        user_id: UUID of the authenticated requester.

    Returns:
        AnalysisChartData when job_id exists, belongs to user_id, and
        status == 'completed'. None when job_id does not exist or
        belongs to a different user.

    Raises:
        AnalysisNotReadyError: job_id exists and belongs to user_id,
            but status is 'pending', 'running', or 'failed' -- or the
            snapshot is missing the ticker a chart fetch requires.
    """
    result = await session.execute(_SQL_LOAD_RESULT, {"job_id": str(job_id)})
    row: Any = result.fetchone()

    if row is None:
        logger.debug(
            "get_analysis_chart_data: no analyses row for job_id=%s",
            job_id,
        )
        return None

    row_user_id = row[0]
    if row_user_id is not None and uuid.UUID(str(row_user_id)) != user_id:
        logger.warning(
            "get_analysis_chart_data: job_id=%s belongs to a different user "
            "-- returning not-found to requester",
            job_id,
        )
        return None

    job_status: str = str(row[1])
    if job_status != "completed":
        logger.info(
            "get_analysis_chart_data: job_id=%s not ready (status=%s)",
            job_id,
            job_status,
        )
        raise AnalysisNotReadyError(status=job_status)

    snapshot = _parse_state_snapshot(row[2], job_id=job_id)
    if snapshot is None:
        logger.error(
            "get_analysis_chart_data: job_id=%s status=completed but "
            "state_snapshot is missing/unparseable -- treating as not ready",
            job_id,
        )
        raise AnalysisNotReadyError(status=job_status)

    ticker = snapshot.get("ticker")
    company_name = snapshot.get("company_name")
    if not isinstance(ticker, str) or not ticker or not isinstance(company_name, str):
        logger.error(
            "get_analysis_chart_data: job_id=%s status=completed but snapshot "
            "has no ticker/company_name -- treating as not ready",
            job_id,
        )
        raise AnalysisNotReadyError(status=job_status)

    data_warnings: list[str] = []

    price_history, price_currency, price_warning = await asyncio.to_thread(
        _fetch_price_history_sync, ticker
    )
    if price_warning is not None:
        data_warnings.append(price_warning)

    financials, financials_warning = await asyncio.to_thread(
        _fetch_financial_trend_sync, ticker
    )
    if financials_warning is not None:
        data_warnings.append(financials_warning)

    valuation = snapshot.get("valuation")
    if not isinstance(valuation, dict):
        data_warnings.append("Valuation data was not available for this analysis.")
        valuation = None

    sentiment = snapshot.get("sentiment")
    if not isinstance(sentiment, dict):
        data_warnings.append("Sentiment data was not available for this analysis.")
        sentiment = None

    risk = snapshot.get("risk")
    if not isinstance(risk, dict):
        data_warnings.append("Risk data was not available for this analysis.")
        risk = None

    return AnalysisChartData(
        job_id=job_id,
        ticker=ticker,
        company_name=company_name,
        price_currency=price_currency,
        price_history=price_history,
        financials=financials,
        valuation=valuation,
        sentiment=sentiment,
        risk=risk,
        data_warnings=data_warnings,
    )
