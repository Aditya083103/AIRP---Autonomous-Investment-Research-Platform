# backend/tests/unit/test_websocket_router.py
"""
Unit tests for T-049: backend/routers/websocket.py

WS /api/v1/analysis/{job_id}/stream

Acceptance criteria verified (from task spec):
  * WebSocket sends event per agent completion
  * frontend receives and displays in order
  * connection closes cleanly

Uses starlette.testclient.TestClient (re-exported by fastapi.testclient),
the documented way to test WebSocket routes -- unlike every other AIRP
router test file, this one cannot use httpx.AsyncClient +
ASGITransport, since that transport has no WebSocket support.
TestClient.websocket_connect() runs the ASGI app on its own background
thread/event loop, so every test function in this file is a plain
synchronous ``def``, not ``async def`` -- matching Starlette's own
WebSocket test examples.

What is faked vs. real
-----------------------
  * backend.routers.websocket.get_analysis_status is patched directly
    (module-level patch, not a dependency override) -- it is a plain
    imported function, not a FastAPI dependency, so this is the
    correct way to control its return value without a real database.
  * app.dependency_overrides[get_settings_dependency] -> test_settings,
    the same pattern every other router test file in this suite uses.
  * backend.routers.websocket.AsyncSessionLocal is patched to a no-op
    async context manager -- _authenticate's own DB read (select(User))
    is exercised against a tiny fake session, mirroring
    test_dependencies_auth.py's _make_session_returning helper.
  * backend.services.ws_broadcaster is NOT mocked -- it is pure
    in-memory asyncio, the same module already exercised end-to-end in
    test_ws_broadcaster.py and test_ws_broadcast_nodes.py.

A real JWT is created via backend.services.auth.create_access_token
with test_settings (the same helper test_dependencies_auth.py and
test_auth_router.py already use), so decode_access_token's signature
verification genuinely succeeds rather than being mocked away.

Per Starlette's TestClient documentation, query parameters for
websocket_connect() must be hard-coded directly into the URL string --
the documented ``params=`` kwarg is dropped for WebSocket URLs.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
import pytest

from backend.config import Settings
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User
from backend.services.analysis import AnalysisStatusResult
from backend.services.auth import create_access_token
from backend.services.ws_broadcaster import (
    _reset_for_testing,
    cast_event,
    publish_event,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_broadcaster_registry() -> Generator[None, None, None]:
    """Mirrors test_ws_broadcaster.py -- the broadcaster registry is
    process-wide state and must not leak between tests."""
    _reset_for_testing()
    yield
    _reset_for_testing()


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="streamer@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture
def auth_token(current_user: User, test_settings: Settings) -> str:
    token, _ = create_access_token(current_user.id, settings=test_settings)
    return token


def _make_fake_session_returning(user: Any) -> AsyncMock:
    """
    Mirrors test_dependencies_auth.py's _make_session_returning --
    a mocked AsyncSession whose execute().scalar_one_or_none() returns
    ``user`` (a User instance or None), which is exactly the one query
    backend.routers.websocket._authenticate performs.
    """
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_async_session_local_patch(fake_session: Any) -> Any:
    """
    Build a callable usable as backend.routers.websocket.AsyncSessionLocal:
    calling it must return an async context manager yielding fake_session,
    matching the real AsyncSessionLocal()'s usage as
    ``async with AsyncSessionLocal() as session: ...``.
    """

    class _FakeAsyncContextManager:
        async def __aenter__(self) -> Any:
            return fake_session

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    def _factory() -> _FakeAsyncContextManager:
        return _FakeAsyncContextManager()

    return _factory


def _make_snapshot(
    job_id: uuid.UUID,
    status: str = "running",
    current_phase: str = "Running DCF valuation and peer comparison",
    completed_nodes: list[str] | None = None,
    progress_percent: int = 50,
    error_message: str | None = None,
) -> AnalysisStatusResult:
    return AnalysisStatusResult(
        job_id=job_id,
        status=status,
        current_phase=current_phase,
        completed_nodes=completed_nodes if completed_nodes is not None else ["planner"],
        progress_percent=progress_percent,
        error_message=error_message,
        requested_at=None,
        started_at=None,
        completed_at=None,
    )


@pytest.fixture
def client(
    current_user: User,
    test_settings: Settings,
) -> Generator[TestClient, None, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    fake_session = _make_fake_session_returning(current_user)
    with patch(
        "backend.routers.websocket.AsyncSessionLocal",
        new=_make_async_session_local_patch(fake_session),
    ):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# 1. Authentication failures -- close code 4401
# ---------------------------------------------------------------------------


class TestAuthenticationFailures:
    def test_missing_token_closes_with_4401(self, client: TestClient) -> None:
        job_id = uuid.uuid4()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v1/analysis/{job_id}/stream") as ws:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_garbage_token_closes_with_4401(self, client: TestClient) -> None:
        job_id = uuid.uuid4()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token=not-a-real-token"
            ) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_token_for_deactivated_user_closes_with_4401(
        self, test_settings: Settings
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings

        inactive_user = User(
            id=uuid.uuid4(),
            email="inactive@example.com",
            password_hash="$2b$12$irrelevant-for-this-test",
            is_active=False,
        )
        token, _ = create_access_token(inactive_user.id, settings=test_settings)
        fake_session = _make_fake_session_returning(inactive_user)

        with patch(
            "backend.routers.websocket.AsyncSessionLocal",
            new=_make_async_session_local_patch(fake_session),
        ):
            test_client = TestClient(app)
            job_id = uuid.uuid4()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_client.websocket_connect(
                    f"/api/v1/analysis/{job_id}/stream?token={token}"
                ) as ws:
                    ws.receive_json()
        assert exc_info.value.code == 4401


# ---------------------------------------------------------------------------
# 2. Job not found / not owned -- close code 4404
# ---------------------------------------------------------------------------


class TestJobNotFound:
    def test_unknown_job_id_closes_with_4404(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(
                    f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
                ) as ws:
                    ws.receive_json()
        assert exc_info.value.code == 4404


# ---------------------------------------------------------------------------
# 3. Initial snapshot -- sent immediately on connect
# ---------------------------------------------------------------------------


class TestInitialSnapshot:
    def test_sends_one_event_immediately_on_connect(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        snapshot = _make_snapshot(job_id, status="running")
        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                event = ws.receive_json()
        assert event["job_id"] == str(job_id)
        assert event["status"] == "running"
        assert event["progress_percent"] == 50

    def test_terminal_snapshot_closes_immediately_after_first_event(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        snapshot = _make_snapshot(
            job_id,
            status="completed",
            completed_nodes=["planner", "pdf_export"],
            progress_percent=100,
        )
        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                event = ws.receive_json()
                assert event["is_final"] is True
                # The server closes right after -- a further receive
                # must raise WebSocketDisconnect(1000), not hang.
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == 1000

    def test_failed_snapshot_is_final(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        snapshot = _make_snapshot(
            job_id,
            status="failed",
            error_message="yfinance timed out",
            progress_percent=40,
        )
        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                event = ws.receive_json()
        assert event["status"] == "failed"
        assert event["is_final"] is True
        assert "yfinance timed out" in event["output_preview"]


# ---------------------------------------------------------------------------
# 4. Live forwarding -- events published after connect are forwarded
#    in order; connection closes cleanly on the final event
# ---------------------------------------------------------------------------


class TestLiveForwarding:
    def test_published_events_are_forwarded_in_order(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        snapshot = _make_snapshot(job_id, status="running", progress_percent=10)

        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                # Consume the initial snapshot event first.
                ws.receive_json()

                first = cast_event(
                    job_id=str(job_id),
                    agent="fundamental_analyst",
                    status="running",
                    output_preview="Score 7/10",
                    progress_percent=20,
                    is_final=False,
                )
                second = cast_event(
                    job_id=str(job_id),
                    agent="technical_analyst",
                    status="running",
                    output_preview="Signal BUY",
                    progress_percent=30,
                    is_final=False,
                )
                final = cast_event(
                    job_id=str(job_id),
                    agent="pdf_export",
                    status="completed",
                    output_preview="PDF exported",
                    progress_percent=100,
                    is_final=True,
                )

                publish_event(str(job_id), first)
                publish_event(str(job_id), second)
                publish_event(str(job_id), final)

                received_first = ws.receive_json()
                received_second = ws.receive_json()
                received_final = ws.receive_json()

        assert received_first["agent"] == "fundamental_analyst"
        assert received_second["agent"] == "technical_analyst"
        assert received_final["agent"] == "pdf_export"
        assert received_final["is_final"] is True

    def test_connection_closes_cleanly_after_final_event(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        snapshot = _make_snapshot(job_id, status="running", progress_percent=10)

        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                ws.receive_json()  # initial snapshot

                final = cast_event(
                    job_id=str(job_id),
                    agent="pdf_export",
                    status="completed",
                    output_preview="PDF exported",
                    progress_percent=100,
                    is_final=True,
                )
                publish_event(str(job_id), final)
                ws.receive_json()

                # Server has closed cleanly (code 1000) -- a further
                # receive must raise, not hang.
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == 1000

    def test_events_for_a_different_job_id_are_not_forwarded(
        self, client: TestClient, auth_token: str
    ) -> None:
        job_id = uuid.uuid4()
        other_job_id = uuid.uuid4()
        snapshot = _make_snapshot(job_id, status="running", progress_percent=10)

        with patch(
            "backend.routers.websocket.get_analysis_status",
            new=AsyncMock(return_value=snapshot),
        ):
            with client.websocket_connect(
                f"/api/v1/analysis/{job_id}/stream?token={auth_token}"
            ) as ws:
                ws.receive_json()  # initial snapshot

                # Published for a DIFFERENT job_id -- must never arrive.
                noise = cast_event(
                    job_id=str(other_job_id),
                    agent="fundamental_analyst",
                    status="running",
                    output_preview="irrelevant",
                    progress_percent=20,
                    is_final=False,
                )
                publish_event(str(other_job_id), noise)

                mine = cast_event(
                    job_id=str(job_id),
                    agent="pdf_export",
                    status="completed",
                    output_preview="PDF exported",
                    progress_percent=100,
                    is_final=True,
                )
                publish_event(str(job_id), mine)

                received = ws.receive_json()

        assert received["agent"] == "pdf_export"
