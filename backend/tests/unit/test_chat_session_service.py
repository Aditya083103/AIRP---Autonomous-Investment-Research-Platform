# backend/tests/unit/test_chat_session_service.py
"""
Unit tests for T-103/T-104: backend/services/chat_session_service.py

T-107 gap this file closes
------------------------------------------------------------------------
test_chat_router.py (T-103) and test_chat_stream_router.py (T-104) both
patch every backend.services.chat_session_service function directly at
the router boundary (their own docstrings say so explicitly) -- which
means this 677-line service module's OWN internal logic (the
memo-scoped analysis-readiness check, the count+page pagination
queries, the ownership checks, the two-write append_chat_message
transaction) had never actually been exercised by any test until this
file. This is the single largest coverage gap T-107's "coverage >85%
for new chat module" acceptance criterion identifies -- every other
chat-module file already had a dedicated test file before this task.

Test strategy
-------------
create_chat_session
    portfolio_wide -- no analysis_id validation performed at all
    memo_scoped, analysis exists + completed -- session created
    memo_scoped, analysis does not exist / not owned -- AnalysisNotFoundError
    memo_scoped, analysis exists but not completed -- AnalysisNotReadyError
list_chat_sessions
    empty result -- ChatSessionPage with 0 items, has_more False
    multiple rows -- ChatSessionSummary fields mapped correctly
    has_more True when more rows exist beyond this page
    has_more False on the last page
get_chat_session_messages
    session_id does not exist -- returns None
    session_id belongs to a different user -- returns None
    0 messages -- ChatMessagesPage with empty items, not an error
    N messages -- ChatMessageEntry fields mapped correctly, oldest-first
    has_more True/False
get_chat_session_stream_info
    session_id does not exist -- returns None
    session_id exists -- returns id/user_id/session_type/analysis_id
        (deliberately NOT filtered by user_id -- see this function's
        own docstring for why the caller does that comparison itself)
append_chat_message
    inserts a ChatMessage, updates the parent session's updated_at,
    commits, refreshes, and returns the new row -- including the
    tool_calls/tool_name/tokens_used optional fields both set and
    left at their defaults

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching this codebase's
established Phase 10 chat-feature service-test convention (see
test_preference_service.py, test_chat_service.py). ENVIRONMENT must be
set to 'test' before any backend import.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402

from backend.models.orm import ChatMessage, ChatSession  # noqa: E402
from backend.services.analysis import (  # noqa: E402
    AnalysisNotReadyError,
    AnalysisStatusResult,
)
from backend.services.chat_session_service import (  # noqa: E402
    AnalysisNotFoundError,
    ChatMessageEntry,
    ChatMessagesPage,
    ChatSessionPage,
    ChatSessionStreamInfo,
    ChatSessionSummary,
    append_chat_message,
    create_chat_session,
    get_chat_session_messages,
    get_chat_session_stream_info,
    list_chat_sessions,
)

_NOW = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_status_result(
    job_id: uuid.UUID, status: str = "completed"
) -> AnalysisStatusResult:
    return AnalysisStatusResult(
        job_id=job_id,
        status=status,
        current_phase="Complete" if status == "completed" else "Running",
        completed_nodes=[],
        progress_percent=100 if status == "completed" else 40,
        error_message=None,
        requested_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW if status == "completed" else None,
    )


def _make_session_for_create(commit_side_effect: Any = None) -> AsyncMock:
    """AsyncSession mock for create_chat_session's own add/commit/refresh."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=commit_side_effect)
    session.refresh = AsyncMock()
    return session


def _make_count_and_page_session(total_count: int, rows: list[Any]) -> AsyncMock:
    """
    AsyncSession mock for the count-then-page two-query pattern
    list_chat_sessions and get_chat_session_messages both use.
    """
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=total_count)

    page_result = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=rows)
    page_result.scalars = MagicMock(return_value=scalars_result)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, page_result])
    return session


def _make_chat_session_row(
    user_id: uuid.UUID,
    session_type: str = "portfolio_wide",
    analysis_id: Optional[uuid.UUID] = None,
    title: Optional[str] = None,
) -> ChatSession:
    return ChatSession(
        id=uuid.uuid4(),
        user_id=user_id,
        session_type=session_type,
        analysis_id=analysis_id,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_chat_message_row(
    session_id: uuid.UUID,
    role: str = "user",
    content: str = "Hello",
    tool_calls: Optional[dict[str, Any]] = None,
    tool_name: Optional[str] = None,
    tokens_used: Optional[int] = None,
) -> ChatMessage:
    return ChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_name=tool_name,
        tokens_used=tokens_used,
        created_at=_NOW,
    )


# ---------------------------------------------------------------------------
# AnalysisNotFoundError
# ---------------------------------------------------------------------------


class TestAnalysisNotFoundError:
    def test_carries_the_analysis_id(self) -> None:
        analysis_id = uuid.uuid4()
        err = AnalysisNotFoundError(analysis_id)
        assert err.analysis_id == analysis_id

    def test_message_mentions_the_analysis_id(self) -> None:
        analysis_id = uuid.uuid4()
        err = AnalysisNotFoundError(analysis_id)
        assert str(analysis_id) in str(err)


# ---------------------------------------------------------------------------
# create_chat_session
# ---------------------------------------------------------------------------


class TestCreateChatSessionPortfolioWide:
    @pytest.mark.asyncio
    async def test_creates_without_any_analysis_validation(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(),
        ) as mock_get_status:
            result = await create_chat_session(
                session, user_id=user_id, session_type="portfolio_wide"
            )

        mock_get_status.assert_not_awaited()
        assert result.user_id == user_id
        assert result.session_type == "portfolio_wide"
        assert result.analysis_id is None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_title_forwarded_when_provided(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(),
        ):
            result = await create_chat_session(
                session,
                user_id=user_id,
                session_type="portfolio_wide",
                title="My portfolio questions",
            )

        assert result.title == "My portfolio questions"


class TestCreateChatSessionMemoScoped:
    @pytest.mark.asyncio
    async def test_creates_when_analysis_exists_and_completed(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(return_value=_make_status_result(analysis_id, "completed")),
        ) as mock_get_status:
            result = await create_chat_session(
                session,
                user_id=user_id,
                session_type="memo_scoped",
                analysis_id=analysis_id,
            )

        mock_get_status.assert_awaited_once_with(
            session, job_id=analysis_id, user_id=user_id
        )
        assert result.session_type == "memo_scoped"
        assert result.analysis_id == analysis_id
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_when_analysis_status_is_none(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(AnalysisNotFoundError) as excinfo:
                await create_chat_session(
                    session,
                    user_id=user_id,
                    session_type="memo_scoped",
                    analysis_id=analysis_id,
                )

        assert excinfo.value.analysis_id == analysis_id
        # No row should ever be written for a rejected request.
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_not_ready_when_analysis_still_running(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(return_value=_make_status_result(analysis_id, "running")),
        ):
            with pytest.raises(AnalysisNotReadyError) as excinfo:
                await create_chat_session(
                    session,
                    user_id=user_id,
                    session_type="memo_scoped",
                    analysis_id=analysis_id,
                )

        assert excinfo.value.status == "running"
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_not_ready_when_analysis_failed(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        session = _make_session_for_create()

        with patch(
            "backend.services.chat_session_service.get_analysis_status",
            new=AsyncMock(return_value=_make_status_result(analysis_id, "failed")),
        ):
            with pytest.raises(AnalysisNotReadyError) as excinfo:
                await create_chat_session(
                    session,
                    user_id=user_id,
                    session_type="memo_scoped",
                    analysis_id=analysis_id,
                )

        assert excinfo.value.status == "failed"


# ---------------------------------------------------------------------------
# list_chat_sessions
# ---------------------------------------------------------------------------


class TestListChatSessions:
    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        user_id = uuid.uuid4()
        session = _make_count_and_page_session(total_count=0, rows=[])

        page = await list_chat_sessions(session, user_id=user_id)

        assert isinstance(page, ChatSessionPage)
        assert page.items == []
        assert page.total_count == 0
        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_maps_rows_to_chat_session_summary(self) -> None:
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()
        row = _make_chat_session_row(
            user_id,
            session_type="memo_scoped",
            analysis_id=analysis_id,
            title="TCS chat",
        )
        session = _make_count_and_page_session(total_count=1, rows=[row])

        page = await list_chat_sessions(session, user_id=user_id)

        assert len(page.items) == 1
        summary = page.items[0]
        assert isinstance(summary, ChatSessionSummary)
        assert summary.id == row.id
        assert summary.session_type == "memo_scoped"
        assert summary.analysis_id == analysis_id
        assert summary.title == "TCS chat"
        assert summary.created_at == _NOW
        assert summary.updated_at == _NOW

    @pytest.mark.asyncio
    async def test_has_more_true_when_more_rows_exist(self) -> None:
        user_id = uuid.uuid4()
        rows = [_make_chat_session_row(user_id) for _ in range(5)]
        session = _make_count_and_page_session(total_count=12, rows=rows)

        page = await list_chat_sessions(session, user_id=user_id, limit=5, offset=0)

        assert page.has_more is True

    @pytest.mark.asyncio
    async def test_has_more_false_on_last_page(self) -> None:
        user_id = uuid.uuid4()
        rows = [_make_chat_session_row(user_id) for _ in range(2)]
        session = _make_count_and_page_session(total_count=12, rows=rows)

        page = await list_chat_sessions(session, user_id=user_id, limit=5, offset=10)

        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_limit_and_offset_carried_onto_the_page(self) -> None:
        user_id = uuid.uuid4()
        session = _make_count_and_page_session(total_count=0, rows=[])

        page = await list_chat_sessions(session, user_id=user_id, limit=7, offset=3)

        assert page.limit == 7
        assert page.offset == 3


# ---------------------------------------------------------------------------
# get_chat_session_messages
# ---------------------------------------------------------------------------


class TestGetChatSessionMessages:
    @pytest.mark.asyncio
    async def test_returns_none_when_session_does_not_exist(self) -> None:
        session = AsyncMock()
        owner_result = MagicMock()
        owner_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=owner_result)

        result = await get_chat_session_messages(
            session, user_id=uuid.uuid4(), session_id=uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_session_belongs_to_a_different_user(self) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        session = AsyncMock()
        owner_result = MagicMock()
        owner_result.scalar_one_or_none = MagicMock(return_value=owner_id)
        session.execute = AsyncMock(return_value=owner_result)

        result = await get_chat_session_messages(
            session, user_id=requester_id, session_id=uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_transcript_is_a_page_not_an_error(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        owner_result = MagicMock()
        owner_result.scalar_one_or_none = MagicMock(return_value=user_id)
        count_result = MagicMock()
        count_result.scalar_one = MagicMock(return_value=0)
        page_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=[])
        page_result.scalars = MagicMock(return_value=scalars_result)

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[owner_result, count_result, page_result]
        )

        result = await get_chat_session_messages(
            session, user_id=user_id, session_id=session_id
        )

        assert isinstance(result, ChatMessagesPage)
        assert result.items == []
        assert result.total_count == 0
        assert result.session_id == session_id

    @pytest.mark.asyncio
    async def test_maps_rows_to_chat_message_entry_oldest_first(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        rows = [
            _make_chat_message_row(
                session_id, role="user", content="What was the verdict?"
            ),
            _make_chat_message_row(
                session_id,
                role="assistant",
                content="TCS was rated BUY.",
                tokens_used=42,
            ),
        ]

        owner_result = MagicMock()
        owner_result.scalar_one_or_none = MagicMock(return_value=user_id)
        count_result = MagicMock()
        count_result.scalar_one = MagicMock(return_value=2)
        page_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=rows)
        page_result.scalars = MagicMock(return_value=scalars_result)

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[owner_result, count_result, page_result]
        )

        result = await get_chat_session_messages(
            session, user_id=user_id, session_id=session_id
        )

        assert result is not None
        assert len(result.items) == 2
        first, second = result.items
        assert isinstance(first, ChatMessageEntry)
        assert first.role == "user"
        assert first.content == "What was the verdict?"
        assert second.role == "assistant"
        assert second.content == "TCS was rated BUY."
        assert second.tokens_used == 42

    @pytest.mark.asyncio
    async def test_has_more_reflects_total_vs_page_size(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        rows = [_make_chat_message_row(session_id) for _ in range(3)]

        owner_result = MagicMock()
        owner_result.scalar_one_or_none = MagicMock(return_value=user_id)
        count_result = MagicMock()
        count_result.scalar_one = MagicMock(return_value=10)
        page_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=rows)
        page_result.scalars = MagicMock(return_value=scalars_result)

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[owner_result, count_result, page_result]
        )

        result = await get_chat_session_messages(
            session, user_id=user_id, session_id=session_id, limit=3, offset=0
        )

        assert result is not None
        assert result.has_more is True


# ---------------------------------------------------------------------------
# get_chat_session_stream_info
# ---------------------------------------------------------------------------


class TestGetChatSessionStreamInfo:
    @pytest.mark.asyncio
    async def test_returns_none_when_session_does_not_exist(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.first = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_chat_session_stream_info(session, session_id=uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_info_for_a_memo_scoped_session(self) -> None:
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        analysis_id = uuid.uuid4()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.first = MagicMock(
            return_value=(session_id, user_id, "memo_scoped", analysis_id)
        )
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_chat_session_stream_info(session, session_id=session_id)

        assert isinstance(result, ChatSessionStreamInfo)
        assert result.id == session_id
        assert result.user_id == user_id
        assert result.session_type == "memo_scoped"
        assert result.analysis_id == analysis_id

    @pytest.mark.asyncio
    async def test_returns_info_for_a_portfolio_wide_session(self) -> None:
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.first = MagicMock(
            return_value=(session_id, user_id, "portfolio_wide", None)
        )
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_chat_session_stream_info(session, session_id=session_id)

        assert result is not None
        assert result.session_type == "portfolio_wide"
        assert result.analysis_id is None

    def test_does_not_filter_by_user_id_in_its_signature(self) -> None:
        """This function returns the row's OWNER, not a caller-scoped
        result -- the caller (chat_stream.py) is responsible for
        comparing result.user_id against the connecting user itself.
        Regression guard: this function must never silently start
        filtering by a caller-supplied user_id, which would break that
        contract."""
        import inspect

        sig = inspect.signature(get_chat_session_stream_info)
        assert "user_id" not in sig.parameters


# ---------------------------------------------------------------------------
# append_chat_message
# ---------------------------------------------------------------------------


class TestAppendChatMessage:
    @pytest.mark.asyncio
    async def test_inserts_message_and_updates_session_timestamp(self) -> None:
        session_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        result = await append_chat_message(
            session, session_id=session_id, role="user", content="Hello there"
        )

        assert result.session_id == session_id
        assert result.role == "user"
        assert result.content == "Hello there"
        session.add.assert_called_once()
        # The explicit UPDATE chat_sessions.updated_at, alongside the
        # ORM-managed ChatMessage insert.
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_optional_fields_default_to_none(self) -> None:
        session_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        result = await append_chat_message(
            session, session_id=session_id, role="assistant", content="Hi!"
        )

        assert result.tool_calls is None
        assert result.tool_name is None
        assert result.tokens_used is None

    @pytest.mark.asyncio
    async def test_optional_fields_forwarded_when_provided(self) -> None:
        session_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        result = await append_chat_message(
            session,
            session_id=session_id,
            role="tool",
            content="{'result': 'ok'}",
            tool_calls={"name": "get_portfolio_summary", "args": {}},
            tool_name="get_portfolio_summary",
            tokens_used=17,
        )

        assert result.tool_calls == {"name": "get_portfolio_summary", "args": {}}
        assert result.tool_name == "get_portfolio_summary"
        assert result.tokens_used == 17

    @pytest.mark.asyncio
    async def test_performs_no_ownership_check_of_its_own(self) -> None:
        """Documented trust boundary: append_chat_message never
        queries chat_sessions to verify ownership -- callers (e.g.
        chat_stream.py, after its own get_chat_session_stream_info
        check) are responsible for that. Regression guard: this
        function's session.execute call count must stay exactly 1
        (the UPDATE) -- a second call would indicate an ownership
        check was added without updating this test/doc."""
        session_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        await append_chat_message(
            session, session_id=session_id, role="user", content="hi"
        )

        assert session.execute.await_count == 1
