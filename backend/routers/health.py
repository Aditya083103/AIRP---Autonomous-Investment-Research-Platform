# backend/routers/health.py
"""
AIRP -- Health Check Router (T-045)

A single, dependency-free liveness endpoint used by:
  * The T-045 acceptance criterion ("GET /health returns 200")
  * Render's health check probe in production (Phase 8 deployment)
  * Local smoke testing immediately after `uvicorn` starts

Deliberately does NOT check downstream dependencies (PostgreSQL, Redis,
ChromaDB). A liveness probe must answer "is this process up and able to
respond" -- mixing that with a readiness probe ("can it reach the DB")
makes Render restart a perfectly healthy process just because Postgres
had a transient blip. A separate /health/ready endpoint with dependency
checks can be added in a later task if the deployment platform needs it.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings

router = APIRouter(tags=["health"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Shape of the GET /health response body."""

    status: Literal["ok"]
    environment: str
    version: str


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 with basic process metadata if the API is up.",
)
async def health_check() -> HealthResponse:
    """Return a static OK payload -- proves the ASGI app is serving requests."""
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version="0.1.0",
    )
