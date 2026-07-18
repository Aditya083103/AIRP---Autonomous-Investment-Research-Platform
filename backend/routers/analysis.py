# backend/routers/analysis.py
"""
AIRP -- Analysis Trigger, Status, Result, Charts & History Router
(T-047 / T-048 / T-050 / T-062)

POST /api/v1/analysis/start (T-047)
GET  /api/v1/analysis/{job_id}/status (T-048)
GET  /api/v1/analysis/{job_id}/result (T-050)
GET  /api/v1/analysis/{job_id}/charts (T-062)
GET  /api/v1/analysis/{job_id}/memo/pdf (T-050)
GET  /api/v1/analysis/history (T-050)

T-047 acceptance criteria (from task spec):
  * Endpoint returns job_id in <200ms
  * Pipeline starts in background
  * Job record in DB

T-048 acceptance criteria (from task spec):
  * Status updates reflect actual pipeline progress
  * 404 for unknown job_id

T-050 acceptance criteria (from task spec):
  * PDF downloads correctly
  * result JSON matches InvestmentDecision schema
  * history paginates

T-062 acceptance criteria (from task spec, frontend-facing but this
endpoint is what makes it possible):
  * All 5 chart types render with real data

HTTP-layer concerns only (request validation via Pydantic schemas,
authentication via get_current_user, translating service-layer results
into the response schema) -- all ticker resolution, database writes, and
the LangGraph invocation itself live in backend.services.analysis,
mirroring the auth router/service split established in T-046.

Why <200ms is achievable (T-047)
----------------------------------
The synchronous path this handler executes is exactly:
  1. Resolve the ticker (pure Python, no I/O) -- resolve_company.
  2. One SELECT + at most one INSERT for the Company row --
     get_or_create_company.
  3. One INSERT for the Analysis row -- create_analysis_job.
  4. Schedule run_analysis_pipeline via BackgroundTasks.add_task --
     this only registers the coroutine; FastAPI runs it AFTER the
     response has been sent (per Starlette's BackgroundTasks contract),
     so the 60-90 second LangGraph pipeline never appears on this
     request's critical path at all.

Why status reflects ACTUAL progress (T-048)
----------------------------------------------
GET /status never computes or guesses anything about where the pipeline
"should" be. It reads analyses.last_completed_node and analyses.status
-- the exact two columns
backend.services.state_persistence.StatePersistenceService writes
synchronously after every LangGraph node completes (T-033) and on
failure (mark_failed) -- and derives current_phase / completed_nodes /
progress_percent from those two values alone
(backend.services.analysis.compute_progress). Two polls with no
pipeline progress in between return byte-identical phase/percentage
fields, because nothing here is a clock or a guess.

Why a 404 (not 403) for another user's job_id (T-048, T-050)
------------------------------------------------------------------
backend.services.analysis.get_analysis_status and
get_analysis_result both return None both when job_id does not exist
at all and when it exists but belongs to a different user. Returning
404 in both cases (rather than 403 for the ownership-mismatch case)
avoids leaking which job_id UUIDs are valid to a caller who does not
own them. GET /memo/pdf applies the identical 404-for-both-cases rule
via the same get_analysis_status lookup, reused here purely as an
ownership/existence check.

Why GET /result returns 409 (not 404) for a job that exists but is not
yet finished (T-050)
------------------------------------------------------------------------
A job_id the caller legitimately owns, that is still 'pending' or
'running' (or that 'failed' before producing a decision), is not a
"not found" condition -- the resource exists, it simply does not have
the requested representation YET. RFC 9110 reserves 404 for "the
origin server did not find a current representation for the target
resource", which describes the unknown/not-yours case exactly, but
409 Conflict ("the request could not be completed due to a conflict
with the current state of the resource") better describes "ask again
once status is completed" -- a condition the caller can resolve by
waiting, not by using a different job_id. The body still names the
job_id's current status so a client need not also call GET /status to
explain the 409.

Why GET /charts returns 200 with data_warnings rather than failing on
a partial data source (T-062)
------------------------------------------------------------------------
Unlike GET /result (where a malformed decision is a genuine, log-worthy
bug -- portfolio_manager_node's contract guarantees a complete
InvestmentDecision whenever status='completed'), GET /charts combines
data from very different reliability tiers in one response: three
chart sources (valuation, sentiment, risk) are already-computed agent
output read straight out of state_snapshot, while two (price history,
revenue/profit trend) require a fresh, LIVE yFinance call made at
request time -- a call that can fail for reasons that have nothing to
do with whether the analysis itself succeeded (a transient network
blip, a ticker yFinance has since delisted). Treating any one of the
five sources as required would mean an otherwise-perfectly-good
analysis occasionally can't show ANY chart because, say, revenue data
timed out. backend.services.analysis.get_analysis_chart_data degrades
each source independently instead: a missing/failed source becomes an
empty list or null for that one field, plus a plain-English note in
data_warnings, so the frontend can render the four charts that did
come back and show a small "unavailable" state for the one that didn't.

Why GET /memo/pdf returns the SAME error response shape as a missing
analysis row when the PDF file itself is absent (T-050)
------------------------------------------------------------------------
A PDF can be legitimately absent even for a 'completed' analysis: T-043's
pdf_export_node degrades to memo_pdf_path=None (not a pipeline failure)
when WeasyPrint is not installed, when feature_pdf_enabled is False, or
when rendering itself failed -- in every one of those cases the
Markdown memo is still available via GET /result's executive_summary/
investment_thesis/etc. fields, just not as a PDF. The endpoint resolves
the deterministic on-disk path via
backend.services.pdf_export.resolve_memo_pdf_path(job_id) and checks
its existence directly with Path.is_file() rather than trusting
state["memo_pdf_path"] from the (potentially stale, if the pipeline
state_snapshot predates a since-deleted file) state_snapshot --
filesystem reality is the single source of truth for "can this be
downloaded right now", and resolve_memo_pdf_path is a pure, deterministic
function of job_id alone (see backend.services.pdf_export module
docstring), so no extra database read is needed beyond the ownership
check GET /status already performs.

Why GET /history uses limit/offset rather than a cursor (T-050)
---------------------------------------------------------------------
The acceptance criterion asks for "history paginates" against a
single user's own analyses -- a collection that, for a portfolio
project's realistic usage, never approaches the row counts where
limit/offset's well-known performance cliff (the database must still
scan and discard every skipped row) becomes a practical concern.
limit/offset also lets a client jump to an arbitrary page directly
(e.g. "page 3") without first walking through a cursor chain, which is
the more natural UI for a paginated dashboard table -- the use case
this endpoint actually serves, as opposed to an infinite-scroll feed
where a cursor would be the better fit.
"""

import logging
from pathlib import Path
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.models.orm import User
from backend.models.schemas import (
    AnalysisChartDataResponse,
    AnalysisStartRequest,
    AnalysisStartResponse,
    AnalysisStatusResponse,
    HistoryEntryResponse,
    HistoryResponse,
    InvestmentDecisionResponse,
    PricePointResponse,
    RevenueProfitPointResponse,
    RiskRadarResponse,
    SentimentChartResponse,
    ValuationChartResponse,
)
from backend.services.analysis import (
    DEFAULT_HISTORY_PAGE_SIZE,
    MAX_HISTORY_PAGE_SIZE,
    AnalysisNotReadyError,
    create_analysis_job,
    get_analysis_chart_data,
    get_analysis_history,
    get_analysis_result,
    get_analysis_status,
    get_or_create_company,
    resolve_company,
    run_analysis_pipeline,
)
from backend.services.pdf_export import resolve_memo_pdf_path

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /api/v1/analysis/start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    response_model=AnalysisStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a new investment analysis",
    description=(
        "Validates the company input, creates an analysis job record in "
        "PostgreSQL with status='pending', and schedules the 8-agent "
        "LangGraph pipeline to run in the background. Returns immediately "
        "with the new job_id -- poll GET /api/v1/analysis/{job_id}/status "
        "or open WS /api/v1/analysis/{job_id}/stream to follow progress."
    ),
)
async def start_analysis(
    body: AnalysisStartRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> AnalysisStartResponse:
    resolution = resolve_company(
        raw_query=body.company_name,
        ticker_override=body.ticker,
        exchange_override=body.exchange,
    )

    company = await get_or_create_company(session, resolution)
    analysis = await create_analysis_job(
        session,
        company=company,
        user_id=current_user.id,
    )

    background_tasks.add_task(
        run_analysis_pipeline,
        job_id=analysis.id,
        company_name=resolution.company_name,
        ticker=resolution.ticker,
        exchange=resolution.exchange,
        requested_by=str(current_user.id),
    )

    return AnalysisStartResponse(
        job_id=analysis.id,
        status=analysis.status,
        company_name=resolution.company_name,
        ticker=resolution.ticker,
        exchange=resolution.exchange,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/status
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/status",
    response_model=AnalysisStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll the status of an analysis job",
    description=(
        "Returns the current lifecycle status, phase, completed nodes, "
        "and progress percentage for an analysis job, read directly from "
        "the same analyses row the LangGraph pipeline updates after every "
        "node completes. Returns 404 if job_id does not exist or belongs "
        "to a different user."
    ),
)
async def get_analysis_status_endpoint(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> AnalysisStatusResponse:
    result = await get_analysis_status(
        session,
        job_id=job_id,
        user_id=current_user.id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis job found for the given job_id",
        )

    return AnalysisStatusResponse(
        job_id=result.job_id,
        status=result.status,
        current_phase=result.current_phase,
        completed_nodes=result.completed_nodes,
        progress_percent=result.progress_percent,
        error_message=result.error_message,
        requested_at=result.requested_at,
        started_at=result.started_at,
        completed_at=result.completed_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/history
# ---------------------------------------------------------------------------
#
# No route in this router is a bare "/{job_id}" (every parameterised
# route has at least one further literal segment after it -- /status,
# /result, /memo/pdf), so "/history" cannot collide with any of them
# regardless of registration order; it is grouped here, immediately
# after the other two-segment routes, purely so every literal-path
# route in this file reads top-to-bottom before the job_id-scoped ones.


@router.get(
    "/history",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List the caller's past analyses, newest first",
    description=(
        "Returns one page of the authenticated user's own analysis jobs, "
        "ordered by requested_at descending. Defaults to the most recent "
        "20 (DEFAULT_HISTORY_PAGE_SIZE); pass limit/offset to page "
        "further. Never returns another user's analyses -- there is no "
        "cross-user history endpoint."
    ),
)
async def get_analysis_history_endpoint(
    limit: int = Query(
        default=DEFAULT_HISTORY_PAGE_SIZE,
        ge=1,
        le=MAX_HISTORY_PAGE_SIZE,
        description="Maximum number of analyses to return on this page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of most-recent analyses to skip before this page",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> HistoryResponse:
    page = await get_analysis_history(
        session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return HistoryResponse(
        items=[
            HistoryEntryResponse(
                job_id=entry.job_id,
                company_name=entry.company_name,
                ticker=entry.ticker,
                exchange=entry.exchange,
                status=entry.status,
                requested_at=entry.requested_at,
                completed_at=entry.completed_at,
                verdict=entry.verdict,
                conviction_score=entry.conviction_score,
            )
            for entry in page.items
        ],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/result
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/result",
    response_model=InvestmentDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the final Investment Decision for a completed analysis",
    description=(
        "Returns the full InvestmentDecision produced by the Portfolio "
        "Manager agent -- verdict, conviction score, price target, and "
        "every Investment Memo section. Returns 404 if job_id does not "
        "exist or belongs to a different user, and 409 if the job exists "
        "but has not yet reached status='completed' (still pending, "
        "running, or it failed before a decision was produced)."
    ),
)
async def get_analysis_result_endpoint(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> InvestmentDecisionResponse:
    try:
        result = await get_analysis_result(
            session,
            job_id=job_id,
            user_id=current_user.id,
        )
    except AnalysisNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Analysis job_id={job_id} is not ready yet "
                f"(status='{exc.status}'). Poll GET /status or open "
                "WS /stream until status='completed', then retry."
            ),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis job found for the given job_id",
        )

    decision = result.decision
    try:
        return InvestmentDecisionResponse(
            agent_name=decision.get("agent_name", "portfolio_manager"),
            analysis_id=decision.get("analysis_id", str(job_id)),
            company_name=decision.get("company_name", ""),
            ticker=decision.get("ticker", ""),
            generated_at=decision["generated_at"],
            error=decision.get("error"),
            verdict=decision["verdict"],
            conviction_score=decision["conviction_score"],
            price_target=decision.get("price_target"),
            time_horizon=decision.get("time_horizon", "12 months"),
            executive_summary=decision.get("executive_summary", ""),
            investment_thesis=decision.get("investment_thesis", ""),
            bull_case=decision.get("bull_case", ""),
            bear_case=decision.get("bear_case", ""),
            risk_summary=decision.get("risk_summary", ""),
            valuation_summary=decision.get("valuation_summary", ""),
            key_risks=decision.get("key_risks", []),
            key_catalysts=decision.get("key_catalysts", []),
            contrarian_response=decision.get("contrarian_response", ""),
            debate_rounds_used=decision.get("debate_rounds_used", 1),
            agent_weights=decision.get("agent_weights", {}),
            summary=decision.get("summary", ""),
            fundamental_years_available=result.fundamental_years_available,
        )
    except KeyError as exc:
        # decision is missing one of the three fields with no sensible
        # default (generated_at, verdict, conviction_score) -- should
        # never happen given portfolio_manager_node's contract (it
        # always writes a complete InvestmentDecision.model_dump() in
        # the same return dict that sets status='completed'), but a
        # KeyError surfacing as a bare 500 traceback would be far less
        # useful to debug than a clear log line naming the job_id and
        # the missing field.
        logger.error(
            "get_analysis_result_endpoint: job_id=%s has status='completed' "
            "but its decision dict is missing required field %s",
            job_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Analysis result data is malformed -- please contact support",
        ) from exc


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/charts
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/charts",
    response_model=AnalysisChartDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve chart-ready data for a completed analysis (T-062)",
    description=(
        "Returns the 1-year price series, 4-year revenue/profit trend, "
        "P/E-vs-peers valuation data, sentiment gauge data, and risk "
        "radar data for a completed analysis. Returns 404 if job_id "
        "does not exist or belongs to a different user, and 409 if the "
        "job exists but has not yet reached status='completed'. Each "
        "of the five chart sources degrades independently -- a "
        "missing agent output or a failed live yFinance call empties "
        "that one field and adds a note to data_warnings rather than "
        "failing the whole response."
    ),
)
async def get_analysis_charts_endpoint(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> AnalysisChartDataResponse:
    try:
        chart_data = await get_analysis_chart_data(
            session,
            job_id=job_id,
            user_id=current_user.id,
        )
    except AnalysisNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Analysis job_id={job_id} is not ready yet "
                f"(status='{exc.status}'). Poll GET /status or open "
                "WS /stream until status='completed', then retry."
            ),
        ) from exc

    if chart_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis job found for the given job_id",
        )

    valuation = chart_data.valuation
    sentiment = chart_data.sentiment
    risk = chart_data.risk

    return AnalysisChartDataResponse(
        job_id=str(chart_data.job_id),
        ticker=chart_data.ticker,
        company_name=chart_data.company_name,
        price_currency=chart_data.price_currency,
        price_history=[
            PricePointResponse(**point) for point in chart_data.price_history
        ],
        financials=[
            RevenueProfitPointResponse(**point) for point in chart_data.financials
        ],
        valuation=(
            ValuationChartResponse(
                pe_ratio=valuation.get("pe_ratio"),
                sector_avg_pe=valuation.get("sector_avg_pe"),
                pb_ratio=valuation.get("pb_ratio"),
                sector_avg_pb=valuation.get("sector_avg_pb"),
                ev_ebitda=valuation.get("ev_ebitda"),
                sector_avg_ev_ebitda=valuation.get("sector_avg_ev_ebitda"),
                peer_tickers=valuation.get("peer_tickers", []),
            )
            if valuation is not None
            else None
        ),
        sentiment=(
            SentimentChartResponse(
                sentiment_score=sentiment.get("sentiment_score", 0.0),
                sentiment_label=sentiment.get("sentiment_label", "neutral"),
                articles_analysed=sentiment.get("articles_analysed", 0),
                positive_articles=sentiment.get("positive_articles", 0),
                negative_articles=sentiment.get("negative_articles", 0),
                neutral_articles=sentiment.get("neutral_articles", 0),
            )
            if sentiment is not None
            else None
        ),
        risk=(
            RiskRadarResponse(
                risk_score=risk.get("risk_score", 1),
                governance_risk=risk.get("governance_risk", 1),
                regulatory_risk=risk.get("regulatory_risk", 1),
                financial_risk=risk.get("financial_risk", 1),
                concentration_risk=risk.get("concentration_risk", 1),
            )
            if risk is not None
            else None
        ),
        data_warnings=chart_data.data_warnings,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/memo/pdf
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/memo/pdf",
    status_code=status.HTTP_200_OK,
    summary="Download the Investment Memo PDF for a completed analysis",
    description=(
        "Streams the branded Investment Memo PDF (T-043) for job_id as "
        "an application/pdf attachment. Returns 404 if job_id does not "
        "exist or belongs to a different user, OR if no PDF exists on "
        "disk for this job (the analysis has not finished, or PDF export "
        "was skipped/unavailable when it ran -- see "
        "backend.services.pdf_export's degrade-to-None behaviour). The "
        "Markdown memo content remains available via GET /result "
        "regardless of whether a PDF was ever produced."
    ),
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "The Investment Memo PDF file",
        },
    },
)
async def download_analysis_memo_pdf(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> FileResponse:
    # Reuses the T-048 status lookup purely as an ownership/existence
    # check -- get_analysis_status's None-for-both-cases contract gives
    # this endpoint the identical "404 either way" behaviour as every
    # other job_id-scoped route, with no separate query of its own.
    status_result = await get_analysis_status(
        session,
        job_id=job_id,
        user_id=current_user.id,
    )
    if status_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis job found for the given job_id",
        )

    pdf_path: Path = resolve_memo_pdf_path(str(job_id))
    if not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No PDF has been generated for this analysis. It may "
                "still be running, or PDF export was unavailable when "
                "it completed -- see GET /result for the Markdown memo "
                "content."
            ),
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"AIRP-Investment-Memo-{job_id}.pdf",
    )
