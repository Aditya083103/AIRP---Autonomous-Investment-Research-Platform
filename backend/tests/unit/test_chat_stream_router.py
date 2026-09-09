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
    get_chat_session_messages / build_memo_context / append_chat_message /
    apply_extracted_preferences (T-106)
    are patched directly (module-level patches, not dependency
    overrides) -- the SAME autouse pipeline-mocking fixture pattern
    T-103's own test_chat_router.py already established for its three
    service-layer calls (itself following test_analysis_router.py's
    patched_pipeline precedent).
  * backend.routers.chat_stream.astream_chat_from_messages is patched
    with a small real async-generator stand-in (not AsyncMock -- see
    _make_astream_chat_from_messages below) so
    ``token_iter = _reply_token_source(...).__aiter__()`` in the
    router's real, unmodified source works exactly as it does against
    the real LangChain streaming call.
  * backend.routers.chat_stream._build_chat_tools and
    .run_tool_calling_round (B9) are patched directly -- these tests
    exercise the ROUTER's own orchestration (does it call the tool
    round, does it fall through to streaming, does a tool-round failure
    surface as an error event), not the tool-calling logic itself,
    which test_chat_llm.py's TestRunToolCallingRound already covers
    exhaustively. The default stub tool round is a no-op passthrough
    (returns the SAME messages it was given, with immediate_text=None)
    so every pre-B9 test's expected token-stream behaviour is
    unaffected unless a test explicitly overrides it.

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
from backend.services.chat_llm import RESPONSE_STYLE_INSTRUCTIONS, ChatLLMError
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
        token_version=0,
    )


@pytest.fixture
def auth_token(current_user: User, test_settings: Settings) -> str:
    # B6: token_version must match current_user's own value (0) --
    # _authenticate rejects a mismatch the same way get_current_user
    # does.
    token, _ = create_access_token(
        current_user.id,
        settings=test_settings,
        token_version=current_user.token_version,
    )
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


def _make_astream_chat_from_messages(
    tokens: list[str],
    error: Exception | None = None,
    calls: list[tuple[Any, Any]] | None = None,
) -> Any:
    """
    A real async-generator function stand-in for
    backend.services.chat_llm.astream_chat_from_messages -- NOT an
    AsyncMock, since the router calls
    ``_reply_token_source(...).__aiter__()`` (which itself delegates to
    this function) directly on the return value the way it would a real
    async generator; AsyncMock's return_value machinery does not make
    that work transparently, but a plain ``async def ...: yield ...``
    function does, by construction.

    ``calls``, when provided, records each invocation's ``(messages,
    llm)`` so a test can assert on exactly what message list (built by
    the real, unmocked ``build_chat_messages``, optionally rewritten by
    a mocked ``run_tool_calling_round``) the router constructed, without
    needing AsyncMock's call-tracking machinery.
    """

    async def _fake(messages: Any, *, llm: Any = None) -> AsyncGenerator[str, None]:
        if calls is not None:
            calls.append((messages, llm))
        for token in tokens:
            yield token
        if error is not None:
            raise error

    return _fake


def _default_tool_round(llm: Any, tools: Any, messages: Any) -> tuple[Any, None]:
    """
    Default stand-in for run_tool_calling_round (B9): a no-op passthrough
    that returns the SAME messages it was given with immediate_text=None
    -- i.e. "no tool needed, proceed to the normal token stream" -- so
    every pre-B9 test's expected start/token.../done behaviour is
    unaffected by the tool round now always running (see
    _build_chat_tools's own docstring for why it is never empty).
    """
    return messages, None


def _make_default_preferences(
    risk_appetite: Any = None,
    preferred_sectors: Any = None,
    chat_response_style: str = "concise",
) -> MagicMock:
    """
    A minimal stand-in for the ``UserPreferences`` row
    ``apply_extracted_preferences`` (T-106) returns -- this router only
    ever reads ``.chat_response_style`` / ``.risk_appetite`` /
    ``.preferred_sectors`` off it, so a MagicMock with exactly those
    three attributes set is a faithful, lightweight substitute for a
    real ORM row in these router-level tests (which already delegate
    all real UserPreferences persistence logic to
    test_preference_service.py's own dedicated unit tests).
    """
    prefs = MagicMock()
    prefs.risk_appetite = risk_appetite
    prefs.preferred_sectors = preferred_sectors if preferred_sectors is not None else []
    prefs.chat_response_style = chat_response_style
    return prefs


def _patch_chat_stream_services(
    *,
    stream_info: Any,
    history_page: Any = None,
    memo_context: Any = None,
    append_side_effect: Any = None,
    astream_tokens: list[str] | None = None,
    astream_error: Exception | None = None,
    preferences: Any = None,
    tools: Any = None,
    tool_round: Any = None,
    cached_reply: str | None = None,
    astream_calls: list[tuple[Any, Any]] | None = None,
) -> Any:
    """
    Bundle the module-level patches every test in this file needs,
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

    B9 additions:
      * ``get_cached_reply`` defaults to returning None (a cache miss)
        so every pre-B9 test still exercises the real tool-round +
        streaming path; pass ``cached_reply`` to simulate a cache hit.
      * ``_build_chat_tools``/``run_tool_calling_round`` are patched to
        a harmless default (some tools exist, but the round is a no-op
        passthrough -- see ``_default_tool_round``) so the tool round
        now always running (B9's tools list is never empty) does not
        change any pre-B9 test's observed start/token.../done sequence
        unless a test explicitly overrides ``tools``/``tool_round``.
      * ``set_cached_reply``/``get_chat_llm`` are patched too, purely so
        no test in this file (which never wants a real Redis round-trip
        or a real LLM client construction) can accidentally reach past
        the mocked layer.
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
        # T-106: apply_extracted_preferences does real database I/O
        # (select-or-insert into user_preferences, then a possible
        # write-once update) -- patched here the same way the other
        # four service-layer calls already are, rather than exercised
        # against the fake AsyncSessionLocal, whose execute() always
        # returns `current_user` regardless of query (see the `client`
        # fixture) and is in no way a working stand-in for a real
        # UserPreferences table. Persistence logic itself (write-once,
        # lazy creation, the race fallback) is covered independently
        # by test_preference_service.py.
        "apply_extracted_preferences": AsyncMock(
            return_value=(
                preferences if preferences is not None else _make_default_preferences()
            )
        ),
        # B9
        "get_cached_reply": MagicMock(return_value=cached_reply),
        "set_cached_reply": MagicMock(return_value=None),
        "_build_chat_tools": MagicMock(
            return_value=tools if tools is not None else [MagicMock(name="fake_tool")]
        ),
        "run_tool_calling_round": AsyncMock(
            side_effect=tool_round if tool_round is not None else _default_tool_round
        ),
        "get_chat_llm": MagicMock(return_value=MagicMock(name="fake_llm")),
    }
    astream_replacement = _make_astream_chat_from_messages(
        astream_tokens or [], astream_error, calls=astream_calls
    )

    @contextmanager
    def _apply() -> Generator[dict[str, Any], None, None]:
        with ExitStack() as stack:
            for name, mock in mocks.items():
                stack.enter_context(
                    patch(f"backend.routers.chat_stream.{name}", new=mock)
                )
            stack.enter_context(
                patch(
                    "backend.routers.chat_stream.astream_chat_from_messages",
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

    def test_start_event_carries_the_persisted_user_messages_id(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """B9 edit-and-resend: 'start' must carry the id
        append_chat_message just assigned to the USER's turn (not the
        assistant's, which does not exist yet at 'start' time) -- see
        chat_stream.py's module docstring, "Why 'start' now carries
        the user message's id"."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        user_message_id = uuid.uuid4()
        assistant_message_id = uuid.uuid4()

        def _role_aware_append(*_args: Any, **kwargs: Any) -> MagicMock:
            saved = MagicMock()
            saved.id = (
                user_message_id
                if kwargs.get("role") == "user"
                else assistant_message_id
            )
            return saved

        with _patch_chat_stream_services(
            stream_info=info,
            astream_tokens=["hi"],
            append_side_effect=_role_aware_append,
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                start = ws.receive_json()
                ws.receive_json()  # token
                done = ws.receive_json()

        assert start["event_type"] == "start"
        assert start["message_id"] == str(user_message_id)
        assert done["message_id"] == str(assistant_message_id)
        assert start["message_id"] != done["message_id"]

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
        converted into HumanMessage/AIMessage turns (via the real,
        unmocked build_chat_messages) and forwarded to
        astream_chat_from_messages as part of the conversation."""
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
        recorded_calls: list[tuple[Any, Any]] = []

        with _patch_chat_stream_services(
            stream_info=info,
            history_page=prior_history,
            astream_tokens=["Because..."],
            astream_calls=recorded_calls,
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "Why?"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        assert len(recorded_calls) == 1
        forwarded_messages, _llm = recorded_calls[0]
        # [SystemMessage, prior user turn, prior assistant turn, new user turn]
        assert len(forwarded_messages) == 4
        assert forwarded_messages[1].content == "What was the verdict on TCS?"
        assert forwarded_messages[2].content == "AIRP rated TCS a BUY."
        assert forwarded_messages[3].content == "Why?"

    def test_each_turn_requests_the_full_transcript_page_not_a_truncated_one(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """B9 follow-up/multi-turn verification: every turn must ask
        get_chat_session_messages for the FULL MAX_MESSAGES_PAGE_SIZE
        page (offset 0, no smaller hard-coded cap) so a long-running
        conversation's earlier turns are never silently dropped from
        the context a follow-up question is answered against."""
        from backend.services.chat_session_service import MAX_MESSAGES_PAGE_SIZE

        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)

        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["ok"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "first question"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

                ws.send_json({"message": "follow-up question"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        history_mock = mocks["get_chat_session_messages"]
        assert history_mock.await_count == 2
        for call in history_mock.await_args_list:
            assert call.kwargs["limit"] == MAX_MESSAGES_PAGE_SIZE
            assert call.kwargs.get("session_id") == session_id


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

        async def _slow_astream_chat_from_messages(
            messages: Any, *, llm: Any = None
        ) -> AsyncGenerator[str, None]:
            await asyncio.sleep(0.3)  # several poll intervals
            yield "finally "
            yield "here"

        with _patch_chat_stream_services(stream_info=info):
            with patch(
                "backend.routers.chat_stream.astream_chat_from_messages",
                new=_slow_astream_chat_from_messages,
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
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["ok"]
        ) as mocks:
            mocks["build_memo_context"].side_effect = AnalysisNotReadyError(
                status="running"
            )
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


# ---------------------------------------------------------------------------
# 7. Personalization wiring (T-106)
# ---------------------------------------------------------------------------
#
# The actual extraction/persistence LOGIC (write-once, lazy row
# creation, the creation-race fallback) is covered independently and
# exhaustively by test_preference_service.py and
# test_preference_extractor.py -- these tests only prove this router
# calls apply_extracted_preferences with the right arguments on every
# turn, and forwards its return value's three fields into astream_chat
# correctly, matching this task's "user_preferences populated after
# first relevant exchange" acceptance criterion end to end at the
# router layer.


class TestPersonalizationWiring:
    def test_apply_extracted_preferences_called_with_the_users_message(
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
                ws.send_json({"message": "I'm a conservative investor."})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        apply_mock = mocks["apply_extracted_preferences"]
        apply_mock.assert_awaited_once()
        call_args = apply_mock.call_args
        # (session, user_id, extraction) -- positional per
        # backend.routers.chat_stream's own call site.
        assert call_args.args[1] == current_user.id
        extraction = call_args.args[2]
        assert extraction.risk_appetite == "conservative"

    def test_preferences_return_value_forwarded_into_astream_chat(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """response_style/risk_appetite/preferred_sectors now reach the
        model via the built SystemMessage's content (build_chat_messages
        -> build_system_prompt), not as separate astream_chat_from_messages
        kwargs -- assert on that content instead."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        recorded_calls: list[tuple[Any, Any]] = []
        stub_preferences = _make_default_preferences(
            risk_appetite="aggressive",
            preferred_sectors=["IT", "Auto"],
            chat_response_style="detailed",
        )

        with _patch_chat_stream_services(
            stream_info=info,
            astream_tokens=["ok"],
            astream_calls=recorded_calls,
            preferences=stub_preferences,
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "what's the verdict?"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        assert len(recorded_calls) == 1
        forwarded_messages, _llm = recorded_calls[0]
        system_content = forwarded_messages[0].content
        assert RESPONSE_STYLE_INSTRUCTIONS["detailed"] in system_content
        assert "risk appetite: aggressive" in system_content
        assert "IT, Auto" in system_content

    def test_default_preferences_stub_forwards_concise_and_unknowns(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """When nothing is known yet (a brand-new user's first ever
        turn), the built system prompt still carries the concise
        instruction and the "ask once" personalization block -- exactly
        what chat_llm.build_personalization_instruction produces for
        risk_appetite=None/preferred_sectors=[]."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        recorded_calls: list[tuple[Any, Any]] = []
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["ok"], astream_calls=recorded_calls
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                ws.receive_json()  # start
                ws.receive_json()  # token
                ws.receive_json()  # done

        assert mocks["apply_extracted_preferences"].await_count == 1
        assert len(recorded_calls) == 1
        forwarded_messages, _llm = recorded_calls[0]
        system_content = forwarded_messages[0].content
        assert RESPONSE_STYLE_INSTRUCTIONS["concise"] in system_content
        # build_personalization_instruction's "nothing known yet" branch --
        # confirms risk_appetite=None/preferred_sectors=[] actually reached it.
        assert "do not yet know this user's risk appetite" in system_content

    def test_apply_extracted_preferences_called_once_per_turn_not_per_connection(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """Two turns on the same connection -> two independent
        apply_extracted_preferences calls, each free to learn something
        new (or not) -- personalization is evaluated every turn, the
        same way response_style/context already are."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["ok"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "first message"})
                ws.receive_json()
                ws.receive_json()
                ws.receive_json()

                ws.send_json({"message": "second message"})
                ws.receive_json()
                ws.receive_json()
                ws.receive_json()

        assert mocks["apply_extracted_preferences"].await_count == 2


# ---------------------------------------------------------------------------
# 8. Tool binding (B9) -- _build_chat_tools
#
# Root cause this closes: the router used to bind NO tools at all for a
# portfolio-wide session (a documented "known scope boundary" -- see the
# module docstring) -- the assistant had no way to look up the user's own
# analyses, so a portfolio-wide question about a specific past analysis
# produced a false "analysis has not been done" even when the user had one.
# ---------------------------------------------------------------------------


class TestBuildChatTools:
    def test_memo_scoped_session_gets_only_the_live_data_tools(self) -> None:
        from backend.routers.chat_stream import _build_chat_tools
        from backend.tools.ratios import fetch_ratios
        from backend.tools.stock_price import fetch_stock_price

        tools = _build_chat_tools(
            MagicMock(), MagicMock(id=uuid.uuid4()), "memo_scoped"
        )

        assert tools == [fetch_ratios, fetch_stock_price]

    def test_portfolio_wide_session_gets_portfolio_tools_plus_live_data_tools(
        self,
    ) -> None:
        from backend.routers.chat_stream import _build_chat_tools
        from backend.tools.ratios import fetch_ratios
        from backend.tools.stock_price import fetch_stock_price

        fake_session = MagicMock()
        fake_user = MagicMock(id=uuid.uuid4())
        portfolio_stub_tools = [MagicMock(name="get_user_analyses")]

        with patch(
            "backend.routers.chat_stream.build_portfolio_tools",
            return_value=portfolio_stub_tools,
        ) as mock_build_portfolio_tools:
            tools = _build_chat_tools(fake_session, fake_user, "portfolio_wide")

        mock_build_portfolio_tools.assert_called_once_with(fake_session, fake_user.id)
        assert tools == portfolio_stub_tools + [fetch_ratios, fetch_stock_price]

    def test_tools_are_never_empty_for_either_session_type(self) -> None:
        from backend.routers.chat_stream import _build_chat_tools

        for session_type in ("memo_scoped", "portfolio_wide"):
            tools = _build_chat_tools(
                MagicMock(), MagicMock(id=uuid.uuid4()), session_type
            )
            assert len(tools) >= 1


# ---------------------------------------------------------------------------
# 9. Tool-calling round wiring (B9) -- router orchestration only; the tool
#    round's own execution logic (which tool ran, error handling, message
#    shape) is unit-tested exhaustively in
#    test_chat_llm.py::TestRunToolCallingRound.
# ---------------------------------------------------------------------------


class TestToolCallingRoundWiring:
    def test_run_tool_calling_round_is_invoked_for_a_normal_turn(
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
                ws.send_json({"message": "What's TCS's P/E?"})
                ws.receive_json()
                ws.receive_json()
                ws.receive_json()

        mocks["run_tool_calling_round"].assert_awaited_once()

    def test_immediate_text_from_tool_round_is_streamed_with_no_second_llm_call(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        """When the tool round decides no tool is needed, its own
        complete text is delivered as the reply -- astream_chat_from_messages
        (the second, streaming call) is never invoked at all."""
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)

        def _immediate_text(llm: Any, tools: Any, messages: Any) -> tuple[Any, str]:
            return messages, "A P/E ratio compares price to earnings."

        astream_calls: list[tuple[Any, Any]] = []
        with _patch_chat_stream_services(
            stream_info=info, tool_round=_immediate_text, astream_calls=astream_calls
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "What is a P/E ratio?"})
                ws.receive_json()  # start
                token_event = ws.receive_json()
                assert token_event["event_type"] == "token"
                assert token_event["token"] == "A P/E ratio compares price to earnings."
                done = ws.receive_json()
                assert done["event_type"] == "done"

        assert astream_calls == []

    def test_tool_round_failure_produces_an_error_event_not_a_dead_connection(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        call_count = {"n": 0}

        def _raise_once_then_passthrough(
            llm: Any, tools: Any, messages: Any
        ) -> tuple[Any, None]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("tool exploded")
            return messages, None

        with _patch_chat_stream_services(
            stream_info=info,
            tool_round=_raise_once_then_passthrough,
            astream_tokens=["ok"],
        ):
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "Which of my analyses are BUY?"})
                error_event = ws.receive_json()
                assert error_event["event_type"] == "error"
                assert error_event["is_final"] is True

                # Connection survives -- a second turn still works.
                ws.send_json({"message": "try again"})
                start_event = ws.receive_json()
                assert start_event["event_type"] == "start"


# ---------------------------------------------------------------------------
# 10. Reply cache (B9)
# ---------------------------------------------------------------------------


class TestReplyCache:
    def test_cache_hit_skips_the_tool_round_and_the_streaming_call(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        astream_calls: list[tuple[Any, Any]] = []
        with _patch_chat_stream_services(
            stream_info=info,
            cached_reply="You have 3 BUY calls (cached).",
            astream_calls=astream_calls,
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "Which of my analyses are BUY?"})
                ws.receive_json()  # start
                token_event = ws.receive_json()
                assert token_event["token"] == "You have 3 BUY calls (cached)."
                done = ws.receive_json()
                assert done["event_type"] == "done"

        mocks["run_tool_calling_round"].assert_not_called()
        assert astream_calls == []

    def test_cache_miss_checks_the_cache_then_streams_normally(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["fresh ", "reply"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                for _ in range(4):
                    ws.receive_json()

        mocks["get_cached_reply"].assert_called_once()

    def test_fresh_reply_is_cached_after_a_successful_turn(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, astream_tokens=["fresh ", "reply"]
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                for _ in range(4):
                    ws.receive_json()

        mocks["set_cached_reply"].assert_called_once()
        call_args = mocks["set_cached_reply"].call_args
        assert call_args.args[1] == "fresh reply"

    def test_a_cache_hit_is_not_re_cached(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        info = _make_stream_info(session_id, user_id=current_user.id)
        with _patch_chat_stream_services(
            stream_info=info, cached_reply="already cached"
        ) as mocks:
            with client.websocket_connect(
                f"/api/v1/chat/{session_id}/stream?token={auth_token}"
            ) as ws:
                ws.send_json({"message": "hello"})
                for _ in range(3):
                    ws.receive_json()

        mocks["set_cached_reply"].assert_not_called()

    def test_cache_key_scoped_to_analysis_id_for_a_memo_scoped_session(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        session_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        info = _make_stream_info(
            session_id,
            user_id=current_user.id,
            session_type="memo_scoped",
            analysis_id=analysis_id,
        )
        with patch(
            "backend.routers.chat_stream.build_cache_key",
            new=MagicMock(return_value="fixed-key"),
        ) as mock_build_key:
            with _patch_chat_stream_services(stream_info=info, astream_tokens=["ok"]):
                with client.websocket_connect(
                    f"/api/v1/chat/{session_id}/stream?token={auth_token}"
                ) as ws:
                    ws.send_json({"message": "hi"})
                    for _ in range(3):
                        ws.receive_json()

        mock_build_key.assert_called_once()
        args = mock_build_key.call_args.args
        assert args[0] == current_user.id
        assert args[1] == str(analysis_id)

    def test_cache_key_uses_the_portfolio_placeholder_for_a_portfolio_wide_session(
        self, client: TestClient, auth_token: str, current_user: User
    ) -> None:
        from backend.services.chat_cache import PORTFOLIO_SCOPE

        session_id = uuid.uuid4()
        info = _make_stream_info(
            session_id, user_id=current_user.id, session_type="portfolio_wide"
        )
        with patch(
            "backend.routers.chat_stream.build_cache_key",
            new=MagicMock(return_value="fixed-key"),
        ) as mock_build_key:
            with _patch_chat_stream_services(stream_info=info, astream_tokens=["ok"]):
                with client.websocket_connect(
                    f"/api/v1/chat/{session_id}/stream?token={auth_token}"
                ) as ws:
                    ws.send_json({"message": "hi"})
                    for _ in range(3):
                        ws.receive_json()

        args = mock_build_key.call_args.args
        assert args[1] == PORTFOLIO_SCOPE
