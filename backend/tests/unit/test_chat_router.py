# backend/tests/unit/test_chat_router.py
"""
Unit tests for T-103: backend/routers/chat.py

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport,
the same pattern as test_analysis_router.py / test_accuracy_router.py /
test_documents_router.py), with:
  * get_async_session overridden to a bare AsyncMock -- every route in
    this router forwards the session straight into a
    backend.services.chat_session_service function, which is itself
    patched per this file's own autouse fixture (see below), so the
    session's actual behaviour is never exercised by these tests. This
    mirrors test_accuracy_router.py's own ``_session_override`` for
    the identical reason.
  * get_current_user overridden directly to a fixed User instance --
    this file is not re-testing JWT verification itself (that is
    T-046's job, already covered by test_auth_router.py /
    test_dependencies_auth.py); it only needs *an* authenticated
    caller, the same scoping note test_analysis_router.py's own
    docstring makes.
  * backend.routers.chat.create_chat_session /
    backend.routers.chat.list_chat_sessions /
    backend.routers.chat.get_chat_session_messages patched to AsyncMock
    by an autouse fixture (patched_chat_service) for EVERY test in this
    module -- the SAME "autouse pipeline-mocking fixture" pattern
    test_analysis_router.py's own patched_pipeline fixture established
    for run_analysis_pipeline, and the pattern this task's own
    acceptance criteria name explicitly. Individual tests configure
    each mock's return_value/side_effect via the same fixture instance
    to exercise one specific router branch (success, 404, 409, or the
    empty-page case) without ever touching a real database.

Acceptance criteria verified (from task spec):
  * All endpoints covered by pytest with the existing autouse
    pipeline-mocking fixture pattern -- every test class below
  * JWT-protected per existing auth pattern -- TestCreateSessionAuth /
    TestListSessionsAuth / TestGetMessagesAuth
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
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
from backend.models.orm import ChatSession, User
from backend.services.chat_session_service import (
    AnalysisNotFoundError,
    AnalysisNotReadyError,
    ChatMessageEntry,
    ChatMessagesPage,
    ChatSessionPage,
    ChatSessionSummary,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="chatter@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@dataclass
class _PatchedChatService:
    """Bundles the three AsyncMocks patched_chat_service installs, so a
    test can configure return_value/side_effect on exactly the one it
    needs without re-deriving the patch target string itself."""

    create_chat_session: AsyncMock
    list_chat_sessions: AsyncMock
    get_chat_session_messages: AsyncMock


@pytest.fixture(autouse=True)
def patched_chat_service(monkeypatch: pytest.MonkeyPatch) -> _PatchedChatService:
    """
    Replace backend.routers.chat's three imported service functions
    with AsyncMocks for every test in this module, autouse=True so no
    test can forget it and accidentally require a real database
    connection. Individual tests retrieve these same mocks via the
    fixture argument to configure return values / assert call args.
    """
    import backend.routers.chat as chat_router_module

    mock_create = AsyncMock()
    mock_list = AsyncMock()
    mock_messages = AsyncMock()

    monkeypatch.setattr(chat_router_module, "create_chat_session", mock_create)
    monkeypatch.setattr(chat_router_module, "list_chat_sessions", mock_list)
    monkeypatch.setattr(chat_router_module, "get_chat_session_messages", mock_messages)

    return _PatchedChatService(
        create_chat_session=mock_create,
        list_chat_sessions=mock_list,
        get_chat_session_messages=mock_messages,
    )


async def _session_override() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock()


@pytest.fixture
async def client(
    current_user: User,
    test_settings: Settings,
    patched_chat_service: _PatchedChatService,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _session_override
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


def _make_chat_session(
    *,
    session_type: str = "portfolio_wide",
    analysis_id: uuid.UUID | None = None,
    title: str | None = None,
) -> ChatSession:
    """A real (unpersisted) ChatSession ORM instance -- plain
    construction, no database involved -- standing in for what
    create_chat_session (mocked) would return on success."""
    return ChatSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_type=session_type,
        analysis_id=analysis_id,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions -- success
# ---------------------------------------------------------------------------


class TestCreateSessionSuccess:
    @pytest.mark.asyncio
    async def test_portfolio_wide_returns_201(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.create_chat_session.return_value = _make_chat_session()
        response = await client.post(
            "/api/v1/chat/sessions", json={"session_type": "portfolio_wide"}
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_response_body_shape(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        fake = _make_chat_session(title="My chat")
        patched_chat_service.create_chat_session.return_value = fake
        response = await client.post(
            "/api/v1/chat/sessions",
            json={"session_type": "portfolio_wide", "title": "My chat"},
        )
        body = response.json()
        assert body["id"] == str(fake.id)
        assert body["session_type"] == "portfolio_wide"
        assert body["analysis_id"] is None
        assert body["title"] == "My chat"
        assert "created_at" in body
        assert "updated_at" in body

    @pytest.mark.asyncio
    async def test_memo_scoped_forwards_analysis_id(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        analysis_id = uuid.uuid4()
        patched_chat_service.create_chat_session.return_value = _make_chat_session(
            session_type="memo_scoped", analysis_id=analysis_id
        )
        response = await client.post(
            "/api/v1/chat/sessions",
            json={"session_type": "memo_scoped", "analysis_id": str(analysis_id)},
        )
        assert response.status_code == 201
        assert response.json()["analysis_id"] == str(analysis_id)

        call_kwargs = patched_chat_service.create_chat_session.call_args.kwargs
        assert call_kwargs["session_type"] == "memo_scoped"
        assert call_kwargs["analysis_id"] == analysis_id

    @pytest.mark.asyncio
    async def test_uses_authenticated_users_id(
        self,
        client: httpx.AsyncClient,
        patched_chat_service: _PatchedChatService,
        current_user: User,
    ) -> None:
        patched_chat_service.create_chat_session.return_value = _make_chat_session()
        await client.post(
            "/api/v1/chat/sessions", json={"session_type": "portfolio_wide"}
        )
        call_kwargs = patched_chat_service.create_chat_session.call_args.kwargs
        assert call_kwargs["user_id"] == current_user.id


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions -- validation (422, service never called)
# ---------------------------------------------------------------------------


class TestCreateSessionValidation:
    @pytest.mark.asyncio
    async def test_memo_scoped_without_analysis_id_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.post(
            "/api/v1/chat/sessions", json={"session_type": "memo_scoped"}
        )
        assert response.status_code == 422
        patched_chat_service.create_chat_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_portfolio_wide_with_analysis_id_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.post(
            "/api/v1/chat/sessions",
            json={
                "session_type": "portfolio_wide",
                "analysis_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 422
        patched_chat_service.create_chat_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_session_type_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.post(
            "/api/v1/chat/sessions", json={"session_type": "not_a_real_type"}
        )
        assert response.status_code == 422
        patched_chat_service.create_chat_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_session_type_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.post("/api/v1/chat/sessions", json={})
        assert response.status_code == 422
        patched_chat_service.create_chat_session.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions -- 404 / 409 from the service layer
# ---------------------------------------------------------------------------


class TestCreateSessionErrors:
    @pytest.mark.asyncio
    async def test_analysis_not_found_returns_404(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        analysis_id = uuid.uuid4()
        patched_chat_service.create_chat_session.side_effect = AnalysisNotFoundError(
            analysis_id
        )
        response = await client.post(
            "/api/v1/chat/sessions",
            json={"session_type": "memo_scoped", "analysis_id": str(analysis_id)},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_analysis_not_ready_returns_409(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.create_chat_session.side_effect = AnalysisNotReadyError(
            status="running"
        )
        response = await client.post(
            "/api/v1/chat/sessions",
            json={
                "session_type": "memo_scoped",
                "analysis_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 409
        assert "running" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions -- auth
# ---------------------------------------------------------------------------


class TestCreateSessionAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        test_settings: Settings,
        patched_chat_service: _PatchedChatService,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _session_override
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        # Deliberately NOT overriding get_current_user here.
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.post(
                "/api/v1/chat/sessions", json={"session_type": "portfolio_wide"}
            )
        assert response.status_code == 401
        patched_chat_service.create_chat_session.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions -- success
# ---------------------------------------------------------------------------


class TestListSessionsSuccess:
    @pytest.mark.asyncio
    async def test_returns_200(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[], total_count=0, limit=20, offset=0
        )
        response = await client.get("/api/v1/chat/sessions")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_body_shape(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        session_id = uuid.uuid4()
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[
                ChatSessionSummary(
                    id=session_id,
                    session_type="portfolio_wide",
                    analysis_id=None,
                    title="My chat",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            ],
            total_count=1,
            limit=20,
            offset=0,
        )
        response = await client.get("/api/v1/chat/sessions")
        body = response.json()
        assert body["total_count"] == 1
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert body["has_more"] is False
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(session_id)
        assert body["items"][0]["title"] == "My chat"

    @pytest.mark.asyncio
    async def test_has_more_true_when_rows_remain(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[
                ChatSessionSummary(
                    id=uuid.uuid4(),
                    session_type="portfolio_wide",
                    analysis_id=None,
                    title=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            ],
            total_count=5,
            limit=1,
            offset=0,
        )
        response = await client.get("/api/v1/chat/sessions?limit=1")
        assert response.json()["has_more"] is True

    @pytest.mark.asyncio
    async def test_default_limit_and_offset_forwarded(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[], total_count=0, limit=20, offset=0
        )
        await client.get("/api/v1/chat/sessions")
        call_kwargs = patched_chat_service.list_chat_sessions.call_args.kwargs
        assert call_kwargs["limit"] == 20
        assert call_kwargs["offset"] == 0

    @pytest.mark.asyncio
    async def test_custom_limit_and_offset_forwarded(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[], total_count=0, limit=5, offset=10
        )
        await client.get("/api/v1/chat/sessions?limit=5&offset=10")
        call_kwargs = patched_chat_service.list_chat_sessions.call_args.kwargs
        assert call_kwargs["limit"] == 5
        assert call_kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_uses_authenticated_users_id(
        self,
        client: httpx.AsyncClient,
        patched_chat_service: _PatchedChatService,
        current_user: User,
    ) -> None:
        patched_chat_service.list_chat_sessions.return_value = ChatSessionPage(
            items=[], total_count=0, limit=20, offset=0
        )
        await client.get("/api/v1/chat/sessions")
        call_kwargs = patched_chat_service.list_chat_sessions.call_args.kwargs
        assert call_kwargs["user_id"] == current_user.id


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions -- validation (limit/offset clamping)
# ---------------------------------------------------------------------------


class TestListSessionsValidation:
    @pytest.mark.asyncio
    async def test_limit_over_max_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get("/api/v1/chat/sessions?limit=1000")
        assert response.status_code == 422
        patched_chat_service.list_chat_sessions.assert_not_called()

    @pytest.mark.asyncio
    async def test_limit_below_one_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get("/api/v1/chat/sessions?limit=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_offset_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get("/api/v1/chat/sessions?offset=-1")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions -- auth
# ---------------------------------------------------------------------------


class TestListSessionsAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        test_settings: Settings,
        patched_chat_service: _PatchedChatService,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _session_override
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get("/api/v1/chat/sessions")
        assert response.status_code == 401
        patched_chat_service.list_chat_sessions.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages -- success
# ---------------------------------------------------------------------------


class TestGetMessagesSuccess:
    @pytest.mark.asyncio
    async def test_returns_200(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        session_id = uuid.uuid4()
        patched_chat_service.get_chat_session_messages.return_value = ChatMessagesPage(
            session_id=session_id, items=[], total_count=0, limit=50, offset=0
        )
        response = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty_items_not_an_error(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        session_id = uuid.uuid4()
        patched_chat_service.get_chat_session_messages.return_value = ChatMessagesPage(
            session_id=session_id, items=[], total_count=0, limit=50, offset=0
        )
        response = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
        body = response.json()
        assert body["items"] == []
        assert body["total_count"] == 0

    @pytest.mark.asyncio
    async def test_response_body_shape_and_transcript_order(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        session_id = uuid.uuid4()
        message_1_id = uuid.uuid4()
        message_2_id = uuid.uuid4()
        patched_chat_service.get_chat_session_messages.return_value = ChatMessagesPage(
            session_id=session_id,
            items=[
                ChatMessageEntry(
                    id=message_1_id,
                    session_id=session_id,
                    role="user",
                    content="What was the verdict on TCS?",
                    tool_calls=None,
                    tool_name=None,
                    tokens_used=None,
                    created_at=_NOW,
                ),
                ChatMessageEntry(
                    id=message_2_id,
                    session_id=session_id,
                    role="assistant",
                    content="AIRP rated TCS a BUY at 8/10.",
                    tool_calls=None,
                    tool_name=None,
                    tokens_used=42,
                    created_at=_NOW,
                ),
            ],
            total_count=2,
            limit=50,
            offset=0,
        )
        response = await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
        body = response.json()
        assert body["session_id"] == str(session_id)
        assert len(body["items"]) == 2
        assert body["items"][0]["id"] == str(message_1_id)
        assert body["items"][0]["role"] == "user"
        assert body["items"][1]["id"] == str(message_2_id)
        assert body["items"][1]["role"] == "assistant"
        assert body["items"][1]["tokens_used"] == 42

    @pytest.mark.asyncio
    async def test_session_id_and_pagination_forwarded(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        session_id = uuid.uuid4()
        patched_chat_service.get_chat_session_messages.return_value = ChatMessagesPage(
            session_id=session_id, items=[], total_count=0, limit=10, offset=5
        )
        await client.get(
            f"/api/v1/chat/sessions/{session_id}/messages?limit=10&offset=5"
        )
        call_kwargs = patched_chat_service.get_chat_session_messages.call_args.kwargs
        assert call_kwargs["session_id"] == session_id
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 5

    @pytest.mark.asyncio
    async def test_uses_authenticated_users_id(
        self,
        client: httpx.AsyncClient,
        patched_chat_service: _PatchedChatService,
        current_user: User,
    ) -> None:
        session_id = uuid.uuid4()
        patched_chat_service.get_chat_session_messages.return_value = ChatMessagesPage(
            session_id=session_id, items=[], total_count=0, limit=50, offset=0
        )
        await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
        call_kwargs = patched_chat_service.get_chat_session_messages.call_args.kwargs
        assert call_kwargs["user_id"] == current_user.id


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages -- 404
# ---------------------------------------------------------------------------


class TestGetMessagesNotFound:
    @pytest.mark.asyncio
    async def test_unknown_session_id_returns_404(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        patched_chat_service.get_chat_session_messages.return_value = None
        response = await client.get(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_other_users_session_returns_404_not_403(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        """The service layer returns None for both 'does not exist' and
        'belongs to someone else' -- the router must not distinguish
        them either, matching every other ownership-scoped endpoint in
        this codebase."""
        patched_chat_service.get_chat_session_messages.return_value = None
        response = await client.get(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages")
        assert response.status_code == 404
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_malformed_session_id_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get("/api/v1/chat/sessions/not-a-uuid/messages")
        assert response.status_code == 422
        patched_chat_service.get_chat_session_messages.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages -- validation
# ---------------------------------------------------------------------------


class TestGetMessagesValidation:
    @pytest.mark.asyncio
    async def test_limit_over_max_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get(
            f"/api/v1/chat/sessions/{uuid.uuid4()}/messages?limit=1000"
        )
        assert response.status_code == 422
        patched_chat_service.get_chat_session_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_offset_returns_422(
        self, client: httpx.AsyncClient, patched_chat_service: _PatchedChatService
    ) -> None:
        response = await client.get(
            f"/api/v1/chat/sessions/{uuid.uuid4()}/messages?offset=-1"
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages -- auth
# ---------------------------------------------------------------------------


class TestGetMessagesAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        test_settings: Settings,
        patched_chat_service: _PatchedChatService,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _session_override
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages")
        assert response.status_code == 401
        patched_chat_service.get_chat_session_messages.assert_not_called()
