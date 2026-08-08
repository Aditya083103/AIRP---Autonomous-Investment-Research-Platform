# backend/tests/unit/test_accuracy_router.py
"""
Unit tests for T-090: backend/routers/accuracy.py

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
same pattern as test_documents_router.py / test_analysis_router.py),
with:
  * get_async_session overridden to yield a bare AsyncMock -- the route
    only forwards this session into run_due_evaluations, which is
    itself patched per-test, so the session's actual behaviour is never
    exercised by these tests.
  * get_settings_dependency overridden to test_settings (T-090's fixed
    accuracy_service_token = "test-accuracy-service-token", set in
    conftest.py).
  * backend.services.accuracy_tracker.run_due_evaluations patched at
    ITS OWN module (not backend.routers.accuracy) -- the router calls
    it via ``from backend.services.accuracy_tracker import
    run_due_evaluations``, which binds the name into the router
    module's namespace at import time, so patching
    ``backend.routers.accuracy.run_due_evaluations`` is what actually
    intercepts the call (patch-where-it's-looked-up, the same rule
    test_documents_router.py's docstring already documents for
    _extract_text_from_pdf_bytes).

Acceptance criteria verified (from task spec):
  * Endpoint rejects unauthenticated calls -- TestRunEndpointAuth
  * (workflow scheduling and workflow_dispatch are verified by
    inspecting .github/workflows/evaluate-verdicts.yml directly, not
    by an HTTP test -- see docs/week-20/T-090-accuracy-scheduled-eval.md)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
import httpx
import pytest

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.services.accuracy_tracker import EvaluationBatchResult

_RUN_URL = "/api/v1/accuracy/run"
_REAL_TOKEN = "test-accuracy-service-token"  # matches conftest.test_settings


async def _session_override() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock()


@pytest.fixture
async def client(test_settings: Settings) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _session_override
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth -- "endpoint rejects unauthenticated calls"
# ---------------------------------------------------------------------------


class TestRunEndpointAuth:
    @pytest.mark.asyncio
    async def test_no_header_returns_401(self, client: httpx.AsyncClient) -> None:
        response = await client.post(_RUN_URL)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            _RUN_URL, headers={"X-Service-Token": "wrong-token"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_token_header_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(_RUN_URL, headers={"X-Service-Token": ""})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthenticated_call_never_reaches_run_due_evaluations(
        self, client: httpx.AsyncClient
    ) -> None:
        with patch(
            "backend.routers.accuracy.run_due_evaluations", new=AsyncMock()
        ) as mock_run:
            await client.post(_RUN_URL)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_secret_configured_rejects_even_the_right_looking_token(
        self, test_settings: Settings
    ) -> None:
        """An unconfigured secret must disable the endpoint entirely --
        see verify_service_token's docstring / test_dependencies_auth.py
        for the unit-level version of this same guarantee."""
        unconfigured = test_settings.model_copy(update={"accuracy_service_token": ""})
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _session_override
        app.dependency_overrides[get_settings_dependency] = lambda: unconfigured

        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.post(_RUN_URL, headers={"X-Service-Token": _REAL_TOKEN})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestRunEndpointSuccess:
    @pytest.mark.asyncio
    async def test_correct_token_returns_200(self, client: httpx.AsyncClient) -> None:
        with patch(
            "backend.routers.accuracy.run_due_evaluations",
            new=AsyncMock(
                return_value=EvaluationBatchResult(
                    due_count=3, evaluated_count=2, skipped_count=1
                )
            ),
        ):
            response = await client.post(
                _RUN_URL, headers={"X-Service-Token": _REAL_TOKEN}
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_body_matches_evaluation_batch_result(
        self, client: httpx.AsyncClient
    ) -> None:
        with patch(
            "backend.routers.accuracy.run_due_evaluations",
            new=AsyncMock(
                return_value=EvaluationBatchResult(
                    due_count=5, evaluated_count=5, skipped_count=0
                )
            ),
        ):
            response = await client.post(
                _RUN_URL, headers={"X-Service-Token": _REAL_TOKEN}
            )
        body = response.json()
        assert body["due_count"] == 5
        assert body["evaluated_count"] == 5
        assert body["skipped_count"] == 0
        assert "ran_at" in body

    @pytest.mark.asyncio
    async def test_zero_due_rows_still_returns_200(
        self, client: httpx.AsyncClient
    ) -> None:
        with patch(
            "backend.routers.accuracy.run_due_evaluations",
            new=AsyncMock(
                return_value=EvaluationBatchResult(
                    due_count=0, evaluated_count=0, skipped_count=0
                )
            ),
        ):
            response = await client.post(
                _RUN_URL, headers={"X-Service-Token": _REAL_TOKEN}
            )
        assert response.status_code == 200
        assert response.json()["due_count"] == 0

    @pytest.mark.asyncio
    async def test_run_due_evaluations_is_called_with_the_request_session(
        self, client: httpx.AsyncClient
    ) -> None:
        mock_run = AsyncMock(
            return_value=EvaluationBatchResult(
                due_count=1, evaluated_count=1, skipped_count=0
            )
        )
        with patch("backend.routers.accuracy.run_due_evaluations", new=mock_run):
            await client.post(_RUN_URL, headers={"X-Service-Token": _REAL_TOKEN})

        mock_run.assert_awaited_once()
        # Called positionally with the session from get_async_session's
        # override -- the router does not pass a `now` argument, so
        # run_due_evaluations defaults it internally (T-089 behaviour).
        args, kwargs = mock_run.call_args
        assert len(args) == 1
        assert "now" not in kwargs

    @pytest.mark.asyncio
    async def test_ran_at_is_a_recent_utc_timestamp(
        self, client: httpx.AsyncClient
    ) -> None:
        before = datetime.now(timezone.utc)
        with patch(
            "backend.routers.accuracy.run_due_evaluations",
            new=AsyncMock(
                return_value=EvaluationBatchResult(
                    due_count=0, evaluated_count=0, skipped_count=0
                )
            ),
        ):
            response = await client.post(
                _RUN_URL, headers={"X-Service-Token": _REAL_TOKEN}
            )
        after = datetime.now(timezone.utc)

        ran_at = datetime.fromisoformat(response.json()["ran_at"])
        if ran_at.tzinfo is None:
            ran_at = ran_at.replace(tzinfo=timezone.utc)
        assert before <= ran_at <= after
