# backend/tests/unit/test_analysis_router.py
"""
Unit tests for T-047: backend/routers/analysis.py

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
same pattern as test_main.py / test_auth_router.py) with:
  * get_async_session overridden to a small in-memory fake session that
    genuinely tracks inserted Company / Analysis rows (not a real
    PostgreSQL connection) -- mirrors test_auth_router.py's
    _FakeAsyncSession for User.
  * get_current_user overridden directly to a fixed User instance --
    T-047 is not re-testing JWT verification (that is T-046's job,
    already covered by test_auth_router.py / test_dependencies_auth.py);
    this file only needs *an* authenticated caller.
  * backend.routers.analysis.run_analysis_pipeline patched to an
    AsyncMock by an autouse fixture (patched_pipeline) for EVERY test in
    this module. Without this, the real background task would call
    backend.graph.graph.get_compiled_graph(), which transitively imports
    every one of the 8 agent modules and LangGraph itself -- far too
    heavy for a unit test, and a correctness risk if a single test in
    this file forgot to patch it while the rest remembered.

Acceptance criteria verified (from task spec):
  * Endpoint returns job_id in <200ms       -- TestLatency
  * Pipeline starts in background           -- TestBackgroundScheduling
  * Job record in DB                        -- TestJobPersistence
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import time
from typing import Any, cast
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI
import httpx
import pytest

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import Analysis, Company, User

# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession -- supports Company select/insert and
# Analysis insert, the only two ORM operations analysis.py performs.
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's Result object."""

    def __init__(self, value: Company | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Company | None:
        return self._value


class _FakeAnalysisSession:
    """
    A tiny in-memory fake of AsyncSession supporting exactly the
    operations backend/services/analysis.py uses:
    execute(select(Company).where(...)), add(), commit(), refresh().

    Not a SQL engine -- inspects the compiled statement's bound
    parameter VALUES (not their auto-generated names) to find which
    Company row, if any, matches the (ticker, exchange) filter. This
    sidesteps any uncertainty about exactly how SQLAlchemy names bind
    parameters for a two-condition .where(a, b) clause -- unlike
    test_auth_router.py's precedent, which only ever filters on one
    column (User.email or User.id) and can safely key off an exact
    name like "email_1".
    """

    def __init__(self) -> None:
        self.companies: dict[uuid.UUID, Company] = {}
        self.analyses: dict[uuid.UUID, Analysis] = {}
        self._pending: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        bound_values = set(compiled.params.values())

        if not bound_values:
            return _FakeResult(None)

        for company in self.companies.values():
            if company.ticker in bound_values and company.exchange in bound_values:
                return _FakeResult(company)
        return _FakeResult(None)

    def add(self, instance: Any) -> None:
        self._pending.append(instance)

    async def commit(self) -> None:
        for instance in self._pending:
            if isinstance(instance, Company):
                if instance.id is None:
                    instance.id = uuid.uuid4()
                self.companies[instance.id] = instance
            elif isinstance(instance, Analysis):
                if instance.id is None:
                    instance.id = uuid.uuid4()
                if instance.status is None:
                    instance.status = "pending"
                self.analyses[instance.id] = instance
        self._pending.clear()

    async def rollback(self) -> None:
        self._pending.clear()

    async def refresh(self, instance: Any) -> None:
        return None


def _make_session_override(shared: _FakeAnalysisSession) -> Any:
    """Build a zero-argument async generator function -- see
    test_auth_router.py's docstring for why a bare lambda does not work
    as a dependency_overrides value for an async-generator dependency."""

    async def _override() -> AsyncGenerator[_FakeAnalysisSession, None]:
        yield shared

    return _override


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeAnalysisSession:
    return _FakeAnalysisSession()


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="analyst@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture(autouse=True)
def patched_pipeline(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """
    Replace backend.routers.analysis.run_analysis_pipeline with an
    AsyncMock for every test in this module, autouse=True so no test can
    forget it and accidentally trigger a real LangGraph invocation.
    Individual tests retrieve this same mock via the fixture argument to
    assert on how it was called.
    """
    import backend.routers.analysis as analysis_router_module

    mock = AsyncMock()
    monkeypatch.setattr(analysis_router_module, "run_analysis_pipeline", mock)
    return mock


@pytest.fixture
async def client(
    fake_session: _FakeAnalysisSession,
    current_user: User,
    test_settings: Settings,
    patched_pipeline: AsyncMock,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/v1/analysis/start -- happy path
# ---------------------------------------------------------------------------


class TestStartAnalysisSuccess:
    @pytest.mark.asyncio
    async def test_returns_202(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Tata Consultancy Services"},
        )
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_returns_job_id(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Infosys"},
        )
        body = response.json()
        assert "job_id" in body
        # Must be a well-formed UUID string.
        uuid.UUID(body["job_id"])

    @pytest.mark.asyncio
    async def test_returns_pending_status(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Wipro"},
        )
        assert response.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_resolves_known_company_name_to_ticker(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Tata Consultancy Services"},
        )
        body = response.json()
        assert body["ticker"] == "TCS.NS"
        assert body["exchange"] == "NSE"

    @pytest.mark.asyncio
    async def test_explicit_ticker_override_is_respected(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Some Co", "ticker": "SOMECO", "exchange": "BSE"},
        )
        body = response.json()
        assert body["ticker"] == "SOMECO.BO"
        assert body["exchange"] == "BSE"

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        fake_session: _FakeAnalysisSession,
        test_settings: Settings,
        patched_pipeline: AsyncMock,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        # Deliberately NOT overriding get_current_user here.
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.post(
                "/api/v1/analysis/start",
                json={"company_name": "TCS"},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/analysis/start -- validation
# ---------------------------------------------------------------------------


class TestStartAnalysisValidation:
    @pytest.mark.asyncio
    async def test_blank_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "   "},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_company_name_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post("/api/v1/analysis/start", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_exchange_override_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS", "exchange": "NYSE"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Job record persisted in DB -- "job record in DB"
# ---------------------------------------------------------------------------


class TestJobPersistence:
    @pytest.mark.asyncio
    async def test_analysis_row_created_in_fake_db(
        self, client: httpx.AsyncClient, fake_session: _FakeAnalysisSession
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS"},
        )
        job_id = uuid.UUID(response.json()["job_id"])
        assert job_id in fake_session.analyses
        assert fake_session.analyses[job_id].status == "pending"

    @pytest.mark.asyncio
    async def test_company_row_created_on_first_analysis(
        self, client: httpx.AsyncClient, fake_session: _FakeAnalysisSession
    ) -> None:
        await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Infosys"},
        )
        assert len(fake_session.companies) == 1
        company = next(iter(fake_session.companies.values()))
        assert company.ticker == "INFY"

    @pytest.mark.asyncio
    async def test_repeat_analysis_of_same_company_reuses_company_row(
        self, client: httpx.AsyncClient, fake_session: _FakeAnalysisSession
    ) -> None:
        await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Infosys"},
        )
        await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Infosys"},
        )
        assert len(fake_session.companies) == 1
        assert len(fake_session.analyses) == 2

    @pytest.mark.asyncio
    async def test_analysis_linked_to_authenticated_user(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeAnalysisSession,
        current_user: User,
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS"},
        )
        job_id = uuid.UUID(response.json()["job_id"])
        assert fake_session.analyses[job_id].user_id == current_user.id


# ---------------------------------------------------------------------------
# Background task scheduling -- "pipeline starts in background"
# ---------------------------------------------------------------------------


class TestBackgroundScheduling:
    @pytest.mark.asyncio
    async def test_pipeline_scheduled_exactly_once(
        self, client: httpx.AsyncClient, patched_pipeline: AsyncMock
    ) -> None:
        """
        Starlette's BackgroundTasks executes registered tasks AFTER the
        response has been sent -- httpx's ASGITransport drives the whole
        ASGI lifecycle including background tasks before `post()`
        returns, so by this point the (patched) background task has
        already run exactly once.
        """
        await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Reliance Industries"},
        )
        patched_pipeline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_scheduled_with_correct_arguments(
        self,
        client: httpx.AsyncClient,
        current_user: User,
        patched_pipeline: AsyncMock,
    ) -> None:
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "Tata Consultancy Services"},
        )
        job_id = uuid.UUID(response.json()["job_id"])

        patched_pipeline.assert_awaited_once()
        _, kwargs = patched_pipeline.call_args
        assert kwargs["job_id"] == job_id
        assert kwargs["ticker"] == "TCS.NS"
        assert kwargs["company_name"] == "Tata Consultancy Services"
        assert kwargs["exchange"] == "NSE"
        assert kwargs["requested_by"] == str(current_user.id)

    @pytest.mark.asyncio
    async def test_pipeline_not_scheduled_on_validation_failure(
        self, client: httpx.AsyncClient, patched_pipeline: AsyncMock
    ) -> None:
        await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "   "},
        )
        patched_pipeline.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pipeline_not_scheduled_without_authentication(
        self,
        fake_session: _FakeAnalysisSession,
        test_settings: Settings,
        patched_pipeline: AsyncMock,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/analysis/start",
                json={"company_name": "TCS"},
            )
        patched_pipeline.assert_not_awaited()


# ---------------------------------------------------------------------------
# Latency -- "returns job_id in <200ms"
# ---------------------------------------------------------------------------


class TestLatency:
    @pytest.mark.asyncio
    async def test_response_returns_quickly_with_pipeline_mocked(
        self, client: httpx.AsyncClient
    ) -> None:
        """
        With the actual LangGraph pipeline replaced by the autouse
        patched_pipeline mock (the real pipeline legitimately takes up
        to ~90 seconds and is not what this acceptance criterion is
        measuring), the synchronous request path is just a ticker
        resolution plus two small in-memory dict operations against the
        fake session, which comfortably completes in well under 200ms.
        """
        start = time.monotonic()
        response = await client.post(
            "/api/v1/analysis/start",
            json={"company_name": "TCS"},
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert response.status_code == 202
        assert elapsed_ms < 200
