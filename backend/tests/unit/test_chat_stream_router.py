# backend/tests/unit/test_chat_stream_router.py
"""
Unit tests for T-104: backend/routers/chat_stream.py

WS /api/v1/chat/{session_id}/stream

Uses starlette.testclient.TestClient (re-exported by fastapi.testclient),
the same documented approach test_websocket_router.py (T-049) already
established for testing WebSocket routes -- httpx.AsyncClient +
ASGITransport has no WebSocket support. Every test function is a plain
synchronous ``def``, matching that precedent.

What is faked vs. real
-----------------------
  * backend.routers.chat_stream.AsyncSessionLocal is patched to a no-op
    async context manager yielding a fake AsyncSession, mirroring
    test_websocket_router.py's own _make_async_session_local_patch --
    used both by _authenticate's select(User) query and by
    _run_one_turn's own AsyncSessionLocal() blocks (whose actual
    database work is entirely delegated to the service functions
    below, so the fake session's content is never itself inspected).
  * backend.routers.chat_stream.get_chat_session_stream_info /
    get_chat_session_messages / build_memo_context / append_chat_message
    are patched directly (module-level patches, not dependency
    overrides) -- the SAME autouse pipeline-mocking fixture pattern
    T-103's own test_chat_router.py already established for its three
    service-layer calls (itself following test_analysis_router.py's
    patched_pipeline precedent).
  * backend.routers.chat_stream.astream_chat is patched with a small
    real async-generator stand-in (not AsyncMock -- see
    _make_astream_chat below) so ``token_iter = astream_chat(...).
    __aiter__()`` in the router's real, unmodified source works
    exactly as it does against the real LangChain streaming call.

A real JWT is created via backend.services.auth.create_access_token
with test_settings, the same helper test_websocket_router.py already
uses, so decode_access_token's signature verification genuinely
succeeds rather than being mocked away.

Acceptance criteria verified (from task spec):
  * Client receives incremental tokens        -- TestIncrementalTokens
  * Connection closes cleanly on completion    -- TestCleanClose
  * Reconnect handled gracefully               -- TestGracefulReconnect

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
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
from backend.services.analysis import AnalysisNotReadyError
from backend.services.auth import create_access_token
from backend.services.chat_llm import ChatLLMError
from backend.services.chat_session_service import (
    ChatMessageEntry,
    ChatMessagesPage,
    ChatSessionStreamInfo,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="chatstreamer@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture
def auth_token(current_user: User, test_settings: Settings) -> str:
    token, _ = create_access_token(current_user.id, settings=test_settings)
    return token


def _make_fake_session_returning(user: Any) -> AsyncMock:
    """Mirrors test_websocket_router.py's own helper -- a mocked
    AsyncSession whose execute().scalar_one_or_none() returns ``user``,
    exactly the one query _authenticate performs."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_async_session_local_patch(fake_session: Any) -> Any:
    """Mirrors test_websocket_router.py's own helper -- builds a
    callable usable as backend.routers.chat_stream.AsyncSessionLocal."""

    class _FakeAsyncContextManager:
        async def __aenter__(self) -> Any:
            return fake_session

        async def __aexit__(self, *exc_info: object) -> None:
            return None

    def _factory() -> _FakeAsyncContextManager:
        return _FakeAsyncContextManager()

    return _factory


def _make_stream_info(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    session_type: str = "portfolio_wide",
    analysis_id: uuid.UUID | None = None,
) -> ChatSessionStreamInfo:
    return ChatSessionStreamInfo(
        id=session_id,
        user_id=user_id,
        session_type=session_type,
        analysis_id=analysis_id,
    )


def _make_empty_history_page(session_id: uuid.UUID) -> ChatMessagesPage:
    return ChatMessagesPage(
        session_id=session_id, items=[], total_count=0, limit=200, offset=0
    )


def _make_astream_chat(
    tokens: list[str],
    error: Exception | None = None,
    calls: list[tuple[Any, Any, dict[str, Any]]] | None = None,
) -> Any:
    """
    A real async-generator function stand-in for
    backend.services.chat_llm.astream_chat -- NOT an AsyncMock, since
    the router calls ``astream_chat(...).__aiter__()`` directly on the
    return value the way it would a real async generator; AsyncMock's
    return_value machinery does not make that work transparently, but
    a plain ``async def ...: yield ...`` function does, by construction.

    ``calls``, when provided, records each invocation's
    (history, user_message, kwargs) so a test can assert on exactly
    what conversation history/context the router built and passed
    through, without needing AsyncMock's call-tracking machinery.
    """

    async def _fake_astream_chat(
        history: Any, user_message: Any, **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        if calls is not None:
            calls.append((history, user_message, kwargs))
        for token in tokens:
            yield token
        if error is not None:
            raise error

    return _fake_astream_chat


def _patch_chat_stream_services(
    *,
    stream_info: Any,
    history_page: Any = None,
    memo_context: Any = None,
    append_side_effect: Any = None,
    astream_tokens: list[str] | None = None,
    astream_error: Exception | None = None,
) -> Any:
    """
    Bundle the 5 module-level patches every test in this file needs,
    matching this router's real import names 1:1. Returns a context
    manager that, on __enter__, yields a plain dict of every mock
    (keyed by attribute name) -- built from individual patch() calls
    composed via ExitStack rather than patch.multiple(), since
    patch.multiple()'s own __enter__ return value only includes
    auto-created (DEFAULT) mocks, not explicitly-provided ones like
    the AsyncMock instances this helper constructs itself; using
    ExitStack sidesteps that distinction entirely and guarantees every
    mock this function creates is always reachable from the returned
    dict.
    """
    saved_message = MagicMock()
    saved_message.id = uuid.uuid4()

    mocks = {
        "get_chat_session_stream_info": AsyncMock(return_value=stream_info),
        "get_chat_session_messages": AsyncMock(
            return_value=(
                history_page
                if history_page is not None
                else _make_empty_history_page(
                    stream_info.id if stream_info else uuid.uuid4()
                )
            )
        ),
        "build_memo_context": AsyncMock(return_value=memo_context),
        "append_chat_message": AsyncMock(
            side_effect=append_side_effect, return_value=saved_message
        ),
    }
    astream_replacement = _make_astream_chat(astream_tokens or [], astream_error)

    @contextmanager
    def _apply() -> Generator[dict[str, Any], None, None]:
        with ExitStack() as stack:
            for name, mock in mocks.items():
                stack.enter_context(
                    patch(f"backend.routers.chat_stream.{name}", new=mock)
                )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.astream_chat",
                    new=astream_replacement,
                )
            )
            yield mocks

    return _apply()


@pytest.fixture
def client(
    current_user: User, test_settings: Settings
) -> Generator[TestClient, None, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings

    fake_session = _make_fake_session_returning(current_user)
    with patch(
        "backend.routers.chat_stream.AsyncSessionLocal",
        new=_make_async_session_local_patch(fake_session),
    ):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# 1. Authentication failures -- close code 4401
# ---------------------------------------------------------------------------


class TestAuthenticationFailures:
    def test_missing_token_closes_with_4401(self, client: TestClient) -> None:
        session_id = uuid.uuid4()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v1/chat/{session_id}/stream") as ws:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_garbage_token_closes_with_4401(self, client: TestClient) -> None:
        session_id = uuid.uuid4()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token=not-a-real-token"
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
            email="inactive-chat@example.com",
            password_hash="$2b$12$irrelevant-for-this-test",
            is_active=False,
        )
        token, _ = create_access_token(inactive_user.id, settings=test_settings)
        fake_session = _make_fake_session_returning(inactive_user)

        with patch(
            "backend.routers.chat_stream.AsyncSessionLocal",
            new=_make_async_session_local_patch(fake_session),
        ):
            test_client = TestClient(app)
            session_id = uuid.uuid4()
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_client.websocket_connect(
                    f"/api/v1/chat/{session_id}/stream?token={token}"
                ) as ws:
                    ws.receive_json()
        assert exc_info.value.code == 4401


# ---------------------------------------------------------------------------
# 2. Session not found / not owned -- close code 4404
# ---------------------------------------------------------------------------


class TestSessionNotFound:
    def test_unknown_session_id_closes_with_4404(
        self, client: TestClient, auth_token: str
    ) -> None:
        session_id = uuid.uuid4()
        with _patch_chat_stream_services(stream_info=None):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(
                    f"/api/v1/chat/{session_id}/stream?token={auth_token}"
                ) as ws:
                    ws.receive_json()
        assert exc_info.value.code == 4404

    def test_other_users_session_closes_with_4404(
        self, client: TestClient, auth_token: str
    ) -> None:
        session_id = uuid.uuid4()
        other_users_info = _make_stream_info(session_id, user_id=uuid.uuid4())
        with _patch_chat_stream_services(stream_info=other_users_info):
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(
                    f"/api/v1/chat/{session_id}/stream?token={auth_token}"
                ) as ws:
                    ws.receive_json()
        assert exc_info.value.code == 4404
        assert exc_info.value.code != 403


# ---------------------------------------------------------------------------
# 3. Incremental tokens -- the first acceptance criterion
# ---------------------------------------------------------------------------


class TestIncrementalTokens:
    def test_receives_a_start_event_then_each_token_separately(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["AIRP ", "rated ", "TCS ", "a ", "BUY."]
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "What was the verdict on TCS?"})

                start = ws.receive_json()
                assert start["event_type"] == "start"
                assert start["is_final"] is False

                received_tokens = []
                while True:
                    event = ws.receive_json()
                    if event["event_type"] == "done":
                        break
                    assert event["event_type"] == "token"
                    received_tokens.append(event["token"])

        assert received_tokens == ["AIRP ", "rated ", "TCS ", "a ", "BUY."]

    def test_done_event_carries_a_message_id(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(stream_info=info, astream_tokens=["hi"]):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                done = ws.receive_json()

        assert done["event_type"] == "done"
        assert done["is_final"] is True
        assert done["message_id"] is not None
        uuid.UUID(done["message_id"])  # must be a well-formed UUID string

    def test_tokens_arrive_in_the_order_the_llm_produced_them(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        ordered_tokens = [str(i) for i in range(10)]
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=ordered_tokens
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "count for me"})
                ws.receive_json()  # start
                collected = []
                while True:
                    event = ws.receive_json()
                    if event["event_type"] == "done":
                        break
                    collected.append(event["token"])

        assert collected == ordered_tokens

    def test_prior_transcript_is_converted_to_role_content_history(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """get_chat_session_messages's ChatMessageEntry rows must be
        converted into plain {"role", "content"} dicts and forwarded to
        astream_chat as the conversation's prior history."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        prior_history = ChatMessagesPage(
            session_id=session_id,
            items=[
                ChatMessageEntry(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    role="user",
                    content="What was the verdict on TCS?",
                    tool_calls=None,
                    tool_name=None,
                    tokens_used=None,
                    created_at=_NOW,
                ),
                ChatMessageEntry(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    role="assistant",
                    content="AIRP rated TCS a BUY.",
                    tool_calls=None,
                    tool_name=None,
                    tokens_used=None,
                    created_at=_NOW,
                ),
            ],
            total_count=2,
            limit=200,
            offset=0,
        )
        recorded_calls: list[tuple[Any, Any, dict[str, Any]]] = []
        astream_replacement = _make_astream_chat(["Because..."], calls=recorded_calls)

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.get_chat_session_stream_info",
                    new=AsyncMock(return_value=info),
                )
            )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.get_chat_session_messages",
                    new=AsyncMock(return_value=prior_history),
                )
            )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.build_memo_context",
                    new=AsyncMock(return_value=None),
                )
            )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.append_chat_message",
                    new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
                )
            )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.astream_chat",
                    new=astream_replacement,
                )
            )
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "Why?"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        assert len(recorded_calls) == 1
        forwarded_history, forwarded_message, _ = recorded_calls[0]
        assert forwarded_history == [
            {"role": "user", "content": "What was the verdict on TCS?"},
            {"role": "assistant", "content": "AIRP rated TCS a BUY."},
        ]
        assert forwarded_message == "Why?"


# ---------------------------------------------------------------------------
# 3b. Regression: a slow token must NOT truncate the reply
# ---------------------------------------------------------------------------


class TestSlowTokenDoesNotTruncateReply:
    """
    Guards against a real bug caught during development: the token
    poll loop originally wrapped ``token_iter.__anext__()`` directly in
    ``asyncio.wait_for(..., timeout=...)``. ``wait_for`` CANCELS its
    awaitable the instant it times out, and cancelling an async
    generator's in-flight ``__anext__()`` call destroys the
    generator's paused state -- every subsequent ``__anext__()`` on
    that same iterator then raises ``StopAsyncIteration`` immediately,
    silently truncating the reply to nothing the moment a single token
    takes longer than the poll interval to arrive (an entirely
    realistic wait for a real LLM provider's first token). The fix
    polls a persisted ``asyncio.Task`` via ``asyncio.wait()`` instead,
    which never cancels on a mere timeout -- only on a genuine exit
    (disconnect, send failure). This test speeds up the module's
    polling constants and makes astream_chat sleep for several poll
    intervals before yielding, so it would fail against the original,
    buggy implementation (zero tokens delivered) and passes against
    the fix (both tokens delivered, plus at least one heartbeat).
    """

    def test_a_slow_first_token_still_arrives_after_heartbeats(
        self,
        client: TestClient,
        auth_token: str,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import backend.routers.chat_stream as chat_stream_module

        monkeypatch.setattr(chat_stream_module, "_TOKEN_POLL_INTERVAL_SECONDS", 0.05)
        monkeypatch.setattr(chat_stream_module, "_HEARTBEAT_AFTER_TICKS", 2)

        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)

        async def _slow_astream_chat(
            history: Any, user_message: Any, **kwargs: Any
        ) -> AsyncGenerator[str, None]:
            await asyncio.sleep(0.3)  # several poll intervals
            yield "finally "
            yield "here"

        with patch.multiple(
            "backend.routers.chat_stream",
            get_chat_session_stream_info=AsyncMock(return_value=info),
            get_chat_session_messages=AsyncMock(
                return_value=_make_empty_history_page(session_id)
            ),
            build_memo_context=AsyncMock(return_value=None),
            append_chat_message=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            astream_chat=_slow_astream_chat,
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "take your time"})

                events = []
                while True:
                    event = ws.receive_json()
                    events.append(event)
                    if event["event_type"] == "done":
                        break

        event_types = [e["event_type"] for e in events]
        tokens = [e["token"] for e in events if e["event_type"] == "token"]

        assert (
            "heartbeat" in event_types
        ), f"expected at least one heartbeat during the slow wait, got {event_types}"
        assert tokens == [
            "finally ",
            "here",
        ], f"reply was truncated -- expected both tokens, got {tokens}"
        assert event_types[-1] == "done"


# ---------------------------------------------------------------------------
# 4. Clean close -- the second acceptance criterion
# ---------------------------------------------------------------------------


class TestCleanClose:
    def test_client_can_disconnect_at_any_time_without_a_server_error(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """A plain client-initiated close (exiting the `with` block with
        no message ever sent) must not raise anything unexpected -- the
        connection accepted, validated ownership, then the client hung
        up; the server's receive loop must exit cleanly."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(stream_info=info):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ):
                pass  # connect, then immediately disconnect

    def test_connection_stays_open_after_one_completed_turn(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """After a 'done' event, the socket must still be usable for a
        second turn on the SAME connection -- this endpoint streams
        many turns per connection, it does not close after one reply."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(stream_info=info, astream_tokens=["ok"]):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "first message"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                first_done = ws.receive_json()
                assert first_done["event_type"] == "done"

                # Socket is still open -- send a second message and get
                # a second full turn back on the same connection.
                ws.send_json({"message": "second message"})
                second_start = ws.receive_json()
                assert second_start["event_type"] == "start"


# ---------------------------------------------------------------------------
# 5. Reconnect handled gracefully -- the third acceptance criterion
# ---------------------------------------------------------------------------


class TestGracefulReconnect:
    def test_a_fresh_connection_after_disconnect_authenticates_and_validates_again(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """Every new connection independently re-authenticates and
        re-validates ownership -- there is no server-side per-connection
        state a reconnect could get out of sync with."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["hi"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "first connection"})
                ws.receive_json()
                ws.receive_json()
                ws.receive_json()
            first_call_count = mocks["get_chat_session_stream_info"].call_count

            # Reconnect -- a brand-new WebSocket connection, same session_id.
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "after reconnect"})
                ws.receive_json()
                ws.receive_json()
                ws.receive_json()
            second_call_count = mocks["get_chat_session_stream_info"].call_count

        assert first_call_count == 1
        assert second_call_count == 2

    def test_malformed_message_gets_an_error_event_not_a_closed_connection(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(stream_info=info, astream_tokens=["ok"]):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"not_a_message_field": "oops"})
                error_event = ws.receive_json()
                assert error_event["event_type"] == "error"

                # Connection is still usable after the bad message.
                ws.send_json({"message": "a real message this time"})
                start_event = ws.receive_json()
                assert start_event["event_type"] == "start"

    def test_empty_message_gets_an_error_event(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(stream_info=info):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "   "})
                error_event = ws.receive_json()
                assert error_event["event_type"] == "error"

    def test_llm_failure_gets_an_error_event_not_a_closed_connection(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info,
            astream_tokens=[],
            astream_error=ChatLLMError("provider is down"),
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                start_event = ws.receive_json()
                assert start_event["event_type"] == "start"
                error_event = ws.receive_json()
                assert error_event["event_type"] == "error"
                assert error_event["is_final"] is True

                # Connection survives the failed turn.
                ws.close()

    def test_memo_scoped_session_not_ready_degrades_instead_of_crashing(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """build_memo_context can raise AnalysisNotReadyError -- the
        turn must still proceed (without grounded context) rather than
        the connection dying."""
        session_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        info = _make_stream_info(
            session_id,
            user_id=current_user.id,
            session_type="memo_scoped",
            analysis_id=analysis_id,
        )
        with patch.multiple(
            "backend.routers.chat_stream",
            get_chat_session_stream_info=AsyncMock(return_value=info),
            get_chat_session_messages=AsyncMock(
                return_value=_make_empty_history_page(session_id)
            ),
            build_memo_context=AsyncMock(
                side_effect=AnalysisNotReadyError(status="running")
            ),
            append_chat_message=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            astream_chat=_make_astream_chat(["ok"]),
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "what's the verdict?"})
                start_event = ws.receive_json()
                assert start_event["event_type"] == "start"
                token_event = ws.receive_json()
                assert token_event["event_type"] == "token"


# ---------------------------------------------------------------------------
# 6. Message persistence
# ---------------------------------------------------------------------------


class TestMessagePersistence:
    def test_user_message_persisted_before_streaming_begins(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["ok"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello there"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        append_mock = mocks["append_chat_message"]
        assert append_mock.call_count == 2  # user turn + assistant turn
        first_call_kwargs = append_mock.call_args_list[0].kwargs
        assert first_call_kwargs["role"] == "user"
        assert first_call_kwargs["content"] == "hello there"

    def test_assistant_message_persists_full_accumulated_text(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["Hello", ", ", "world", "!"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hi"})
                ws.receive_json()
                for _ in range(4):
                    ws.receive_json()
                ws.receive_json()  # done

        append_mock = mocks["append_chat_message"]
        assistant_call_kwargs = append_mock.call_args_list[1].kwargs
        assert assistant_call_kwargs["role"] == "assistant"
        assert assistant_call_kwargs["content"] == "Hello, world!"
