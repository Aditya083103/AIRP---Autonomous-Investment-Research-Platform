# backend/routers/analysis.py
"""
AIRP -- Analysis Trigger Router (T-047)

POST /api/v1/analysis/start.

Acceptance criteria (from task spec):
  * Endpoint returns job_id in <200ms
  * Pipeline starts in background
  * Job record in DB

HTTP-layer concerns only (request validation via Pydantic schemas,
authentication via get_current_user, translating service-layer results
into the response schema) -- all ticker resolution, database writes, and
the LangGraph invocation itself live in backend.services.analysis,
mirroring the auth router/service split established in T-046.

Why <200ms is achievable
-------------------------
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
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.models.orm import User
from backend.models.schemas import AnalysisStartRequest, AnalysisStartResponse
from backend.services.analysis import (
    create_analysis_job,
    get_or_create_company,
    resolve_company,
    run_analysis_pipeline,
)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


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
