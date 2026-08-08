# backend/routers/accuracy.py
"""
AIRP -- Verdict Accuracy Tracker Router (T-090 / T-091)

POST /api/v1/accuracy/run      (T-090)
GET  /api/v1/accuracy/summary  (T-091)
GET  /api/v1/accuracy/history  (T-091)

POST /run triggers one run of backend.services.accuracy_tracker
.run_due_evaluations() -- scores every verdict_outcomes row whose
evaluation_horizon_days has elapsed against its live current price.

This is a machine-to-machine endpoint, not something a logged-in user
calls from the React frontend: it is invoked once a day by the
scheduled .github/workflows/evaluate-verdicts.yml GitHub Actions
workflow (and can be triggered manually via that workflow's
workflow_dispatch trigger for testing). Accordingly it is protected by
verify_service_token (a static shared secret in the X-Service-Token
header), not get_current_user (JWT auth for a real user session) --
see backend.dependencies.auth.verify_service_token's docstring for the
full rationale, including why it fails closed when
ACCURACY_SERVICE_TOKEN is not configured.

GET /summary and GET /history (T-091) are the read side: aggregate and
per-row accuracy data for T-092's public AccuracyPage.tsx dashboard.
Neither has ANY auth dependency -- see
backend.services.accuracy_tracker.get_accuracy_history's docstring for
why these two are deliberately not scoped to a requesting user the way
GET /api/v1/analysis/history (T-050) is: verdict_outcomes rows are not
owned by a user (their only FK is analysis_id), and the task spec
explicitly calls the frontend page this data feeds a "public accuracy
dashboard".

Acceptance criteria (from task spec):
  T-090:
  * Workflow runs daily on schedule           -- see the accompanying
                                                  evaluate-verdicts.yml
  * Endpoint rejects unauthenticated calls    -- verify_service_token
  * Manual workflow_dispatch trigger available
    for testing                               -- see
                                                  evaluate-verdicts.yml
  T-091:
  * /accuracy/summary returns overall + by-verdict + by-conviction
    breakdowns                                -- see
                                                  AccuracySummaryResponse
  * /accuracy/history paginated               -- limit/offset Query
                                                  params, same pattern
                                                  as GET /analysis/history
  * both covered by pytest                    -- see
                                                  test_accuracy_summary_history.py

HTTP-layer concerns only (auth, request validation, translating the
service layer's dataclasses into response schemas) -- all scoring and
aggregation logic lives in backend.services.accuracy_tracker, mirroring
the router/service split every other router in this project follows.
run_due_evaluations(), get_accuracy_summary(), and get_accuracy_history()
are all documented as never raising an exception this router would need
to translate into an HTTP error code, so none of the three routes below
wraps its service call in a defensive try/except.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_async_session
from backend.dependencies.auth import verify_service_token
from backend.models.schemas import (
    AccuracyHistoryEntryResponse,
    AccuracyHistoryResponse,
    AccuracyRunResponse,
    AccuracySummaryResponse,
    ConvictionAccuracyBreakdownResponse,
    VerdictAccuracyBreakdownResponse,
)
from backend.services.accuracy_tracker import (
    DEFAULT_ACCURACY_HISTORY_PAGE_SIZE,
    MAX_ACCURACY_HISTORY_PAGE_SIZE,
    get_accuracy_history,
    get_accuracy_summary,
    run_due_evaluations,
)

router = APIRouter(prefix="/api/v1/accuracy", tags=["accuracy"])


# ---------------------------------------------------------------------------
# POST /api/v1/accuracy/run
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=AccuracyRunResponse,
    dependencies=[Depends(verify_service_token)],
    summary="Score every due verdict_outcomes row against its live price",
    description=(
        "Machine-to-machine endpoint (X-Service-Token header required, "
        "not user JWT auth) that runs one batch of "
        "backend.services.accuracy_tracker.run_due_evaluations(). "
        "Intended to be called once a day by the scheduled "
        "evaluate-verdicts.yml GitHub Actions workflow."
    ),
)
async def run_accuracy_evaluation(
    session: AsyncSession = Depends(get_async_session),
) -> AccuracyRunResponse:
    result = await run_due_evaluations(session)
    return AccuracyRunResponse(
        due_count=result.due_count,
        evaluated_count=result.evaluated_count,
        skipped_count=result.skipped_count,
        ran_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/accuracy/summary (T-091)
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=AccuracySummaryResponse,
    summary="Overall verdict accuracy, by verdict type and conviction bucket",
    description=(
        "Public, platform-wide statistic -- not scoped to the caller -- "
        "on how accurate the Portfolio Manager's past BUY/HOLD/SELL "
        "verdicts have been once scored by "
        "backend.services.accuracy_tracker.run_due_evaluations(). No "
        "authentication required; feeds T-092's public AccuracyPage.tsx "
        "dashboard."
    ),
)
async def get_accuracy_summary_endpoint(
    session: AsyncSession = Depends(get_async_session),
) -> AccuracySummaryResponse:
    summary = await get_accuracy_summary(session)
    return AccuracySummaryResponse(
        total_evaluated=summary.total_evaluated,
        total_pending=summary.total_pending,
        overall_accuracy_pct=summary.overall_accuracy_pct,
        by_verdict=[
            VerdictAccuracyBreakdownResponse(
                verdict=entry.verdict,
                evaluated_count=entry.evaluated_count,
                correct_count=entry.correct_count,
                accuracy_pct=entry.accuracy_pct,
            )
            for entry in summary.by_verdict
        ],
        by_conviction=[
            ConvictionAccuracyBreakdownResponse(
                bucket=entry.bucket,
                label=entry.label,
                min_score=entry.min_score,
                max_score=entry.max_score,
                evaluated_count=entry.evaluated_count,
                correct_count=entry.correct_count,
                accuracy_pct=entry.accuracy_pct,
            )
            for entry in summary.by_conviction
        ],
    )


# ---------------------------------------------------------------------------
# GET /api/v1/accuracy/history (T-091)
# ---------------------------------------------------------------------------


@router.get(
    "/history",
    response_model=AccuracyHistoryResponse,
    summary="List every tracked verdict outcome, newest first",
    description=(
        "Returns one page of ALL verdict_outcomes rows (evaluated or "
        "still pending), ordered by verdict_date descending. Defaults "
        "to the most recent 20 (DEFAULT_ACCURACY_HISTORY_PAGE_SIZE); "
        "pass limit/offset to page further. No authentication required "
        "-- unlike GET /api/v1/analysis/history, this is not scoped to "
        "one user's own analyses."
    ),
)
async def get_accuracy_history_endpoint(
    limit: int = Query(
        default=DEFAULT_ACCURACY_HISTORY_PAGE_SIZE,
        ge=1,
        le=MAX_ACCURACY_HISTORY_PAGE_SIZE,
        description="Maximum number of verdict outcomes to return on this page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of most-recent verdict outcomes to skip before this page",
    ),
    session: AsyncSession = Depends(get_async_session),
) -> AccuracyHistoryResponse:
    page = await get_accuracy_history(session, limit=limit, offset=offset)

    return AccuracyHistoryResponse(
        items=[
            AccuracyHistoryEntryResponse(
                id=entry.id,
                analysis_id=entry.analysis_id,
                ticker=entry.ticker,
                verdict=entry.verdict,
                conviction_score=entry.conviction_score,
                price_at_verdict=entry.price_at_verdict,
                verdict_date=entry.verdict_date,
                evaluation_horizon_days=entry.evaluation_horizon_days,
                price_at_evaluation=entry.price_at_evaluation,
                price_change_pct=entry.price_change_pct,
                directional_correct=entry.directional_correct,
                evaluated_at=entry.evaluated_at,
            )
            for entry in page.items
        ],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )
