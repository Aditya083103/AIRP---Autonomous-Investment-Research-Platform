# backend/routers/accuracy.py
"""
AIRP -- Verdict Accuracy Tracker Router (T-090)

POST /api/v1/accuracy/run

Triggers one run of backend.services.accuracy_tracker
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

Acceptance criteria (from task spec):
  * Workflow runs daily on schedule           -- see the accompanying
                                                  evaluate-verdicts.yml
  * Endpoint rejects unauthenticated calls    -- verify_service_token
  * Manual workflow_dispatch trigger available
    for testing                               -- see
                                                  evaluate-verdicts.yml

HTTP-layer concerns only (auth, translating the service layer's
EvaluationBatchResult dataclass into AccuracyRunResponse) -- all
scoring logic lives in backend.services.accuracy_tracker, mirroring
the router/service split every other router in this project follows.
run_due_evaluations() is documented as never raising (T-089's
"never raises" design decision), so this router does not wrap the call
in a defensive try/except -- there is no documented exception from
that function to translate into an HTTP error code.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_async_session
from backend.dependencies.auth import verify_service_token
from backend.models.schemas import AccuracyRunResponse
from backend.services.accuracy_tracker import run_due_evaluations

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
