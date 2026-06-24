# backend/services/analysis.py
"""
AIRP -- Analysis Trigger Service (T-047)

Business logic backing POST /api/v1/analysis/start. Pure service-layer
code with no FastAPI imports (mirrors backend/services/auth.py) so it
stays independently testable without spinning up an ASGI app; the router
(backend/routers/analysis.py) translates this module's plain return
values and exceptions into the correct HTTP response shape and status
code.

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

Public API
----------
    from backend.services.analysis import (
        TickerResolution,
        resolve_company,
        get_or_create_company,
        create_analysis_job,
        run_analysis_pipeline,
    )
"""

import asyncio
from dataclasses import dataclass
import logging
from typing import Optional, cast
import uuid

from sqlalchemy import select
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
