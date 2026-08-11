# backend/services/chat_session_service.py
"""
AIRP -- Chat Session & Message Service (T-103)

Business logic backing the three T-103 REST endpoints:
    POST /api/v1/chat/sessions
    GET  /api/v1/chat/sessions
    GET  /api/v1/chat/sessions/{session_id}/messages

Pure service-layer code with no FastAPI imports -- mirrors
backend/services/analysis.py and backend/services/auth.py -- so it
stays independently testable without spinning up an ASGI app; the
router (backend/routers/chat.py) translates this module's plain return
values and exceptions into the correct HTTP response shape and status
code.

Why ORM ``select()``, not raw SQL like ``chat_service.py``/
``portfolio_tools.py``
------------------------------------------------------------------------
T-100's ``chat_service.py`` and T-101's ``portfolio_tools.py`` both use
raw ``sqlalchemy.text()`` queries against ``analyses.state_snapshot``
specifically because that column is a T-033-migration-only addition,
never mapped onto the ``Analysis`` ORM model. ``ChatSession`` and
``ChatMessage`` are the opposite case: T-099's migration and its ORM
models (``backend/models/orm.py``) were authored together, every column
this module needs is fully mapped, and ``backend/services/
accuracy_tracker.py``'s own ``get_accuracy_history`` already establishes
the precedent for ORM ``select().order_by().limit().offset()`` plus a
``select(func.count(...))`` sibling for a paginated, user-agnostic
listing endpoint. There is no reason to duplicate raw SQL here when the
ORM already models these two tables completely and correctly.

Why ``create_chat_session`` validates a memo-scoped ``analysis_id`` by
calling ``backend.services.analysis.get_analysis_status`` rather than
querying ``analyses`` directly
------------------------------------------------------------------------
A memo-scoped chat session should only ever be creatable against an
analysis the caller owns AND that has actually finished (T-100's own
``build_memo_context`` requires ``status='completed'`` for exactly this
reason -- there is nothing to chat about yet for a 'pending'/'running'
job, and a 'failed' one has no decision to explain). ``get_analysis_status``
already implements the identical ownership check (None for both
"does not exist" and "exists but is not yours") that every other
analysis-scoped endpoint in this codebase relies on -- reusing it here
means this module's ownership semantics can never drift from
``backend/routers/analysis.py``'s, and it is a light read (no
``state_snapshot`` JSONB parsing) compared to ``get_analysis_result``,
appropriate for a check this function only needs the ``status`` field
from.

Why creating a session is 404-vs-409, matching the analysis router's
own convention, not raised as a single generic "invalid" error
------------------------------------------------------------------------
``AnalysisNotFoundError`` (this module, new) and ``AnalysisNotReadyError``
(imported from ``backend.services.analysis``, reused) let the router
distinguish "that analysis_id does not exist or is not yours" (404,
identical semantics to every other job_id-scoped endpoint) from "that
analysis_id is real and yours, but has not finished yet" (409 Conflict,
identical semantics to ``GET /api/v1/analysis/{job_id}/result``) --
collapsing these into one exception type or one generic 400 would lose
information the router already knows how to act on consistently
elsewhere in the API.

Why ``get_chat_session_messages`` returns ``None`` (not raises) for a
missing/not-owned session, but pagination fields still need a session
to exist
------------------------------------------------------------------------
Mirrors the ``get_analysis_status``/``get_analysis_result`` "None means
not found or not yours" contract used everywhere else in this codebase
-- the router turns ``None`` into a 404 with the same "either way, do
not reveal existence to a non-owner" reasoning
``backend/routers/analysis.py`` documents at length. There is no
analogous "not ready yet" state for a chat session the way there is for
an analysis job (a session is immediately usable for message listing
the moment it is created, even with zero messages -- an empty page is
a perfectly valid response, not an error).

Design decisions
------------------------------------------------------------------------
* NO ``from __future__ import annotations`` -- this module lives beside
  ``backend/services/analysis.py`` and ``backend/services/chat_service.py``,
  both of which give the same reason (breaks Pydantic v2 union
  resolution for modules that import this one).
* Plain ASCII section comments (# ---) -- established AIRP convention.
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* Every dataclass here is "everything the router needs, already
  derived" -- the same pattern ``AnalysisStatusResult``/``HistoryEntry``/
  ``AccuracyHistoryEntry`` already establish -- rather than handing the
  router raw ORM instances directly. This keeps the API response shape
  decoupled from the ORM's column set (e.g. ``ChatSession.user_id`` is
  deliberately never included in ``ChatSessionSummary`` -- it is always
  the caller, and echoing it back would be a no-op field at best and a
  future information-leak risk at worst if this module were ever reused
  for a non-owner-scoped listing).

Public API
----------
    from backend.services.chat_session_service import (
        AnalysisNotFoundError,
        ChatSessionSummary,
        ChatSessionPage,
        ChatMessageEntry,
        ChatMessagesPage,
        DEFAULT_SESSIONS_PAGE_SIZE,
        MAX_SESSIONS_PAGE_SIZE,
        DEFAULT_MESSAGES_PAGE_SIZE,
        MAX_MESSAGES_PAGE_SIZE,
        create_chat_session,
        list_chat_sessions,
        get_chat_session_messages,
    )
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm import ChatMessage, ChatSession
from backend.services.analysis import AnalysisNotReadyError, get_analysis_status

logger = logging.getLogger(__name__)

__all__ = [
    "AnalysisNotFoundError",
    "AnalysisNotReadyError",
    "ChatSessionSummary",
    "ChatSessionPage",
    "ChatMessageEntry",
    "ChatMessagesPage",
    "DEFAULT_SESSIONS_PAGE_SIZE",
    "MAX_SESSIONS_PAGE_SIZE",
    "DEFAULT_MESSAGES_PAGE_SIZE",
    "MAX_MESSAGES_PAGE_SIZE",
    "create_chat_session",
    "list_chat_sessions",
    "get_chat_session_messages",
]

#: Default / maximum page size for GET /api/v1/chat/sessions. A user's
#: own chat session count is expected to stay small relative to
#: MAX_HISTORY_PAGE_SIZE (100, analysis.py) for a portfolio project's
#: realistic usage, so the same limit/offset shape (not a cursor) is
#: appropriate for the identical reason analysis.py's docstring gives.
DEFAULT_SESSIONS_PAGE_SIZE = 20
MAX_SESSIONS_PAGE_SIZE = 100

#: Default / maximum page size for GET /.../messages. Deliberately
#: larger than the sessions page size -- a single conversation can
#: reasonably run to dozens of turns, and a caller rendering a full
#: transcript view wants most of it in one request rather than many
#: small pages.
DEFAULT_MESSAGES_PAGE_SIZE = 50
MAX_MESSAGES_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AnalysisNotFoundError(Exception):
    """
    Raised by ``create_chat_session`` when a memo-scoped request's
    ``analysis_id`` does not exist, or exists but belongs to a
    different user.

    A distinct exception from ``AnalysisNotReadyError`` (imported from
    ``backend.services.analysis``) for the same 404-vs-409 reason that
    module's own docstring gives: the router needs to tell "not yours /
    does not exist" (404) apart from "yours, but not finished yet"
    (409) to respond with the correct status code.
    """

    def __init__(self, analysis_id: uuid.UUID) -> None:
        self.analysis_id = analysis_id
        super().__init__(
            f"No analysis found for analysis_id={analysis_id} "
            "(or it belongs to a different user)"
        )


# ---------------------------------------------------------------------------
# create_chat_session (POST /api/v1/chat/sessions)
# ---------------------------------------------------------------------------


async def create_chat_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_type: str,
    analysis_id: Optional[uuid.UUID] = None,
    title: Optional[str] = None,
) -> ChatSession:
    """
    Create a new chat session for the caller.

    For ``session_type='memo_scoped'``, ``analysis_id`` must already
    have been validated as present by
    ``backend.models.schemas.ChatSessionCreateRequest``'s own
    model-level validator -- this function additionally verifies the
    referenced analysis actually exists, belongs to ``user_id``, and
    has ``status='completed'`` before the row is ever written, so the
    database's own ``ck_chat_sessions_scope_consistency`` CHECK
    constraint is never the first or only line of defence against a
    dangling/invalid ``analysis_id``.

    For ``session_type='portfolio_wide'``, no such check is needed or
    performed -- there is no ``analysis_id`` to validate.

    Args:
        session:      Active AsyncSession for this request.
        user_id:      UUID of the authenticated requester -- the new
                       session always belongs to this user.
        session_type: 'memo_scoped' or 'portfolio_wide' (already
                       validated by the request schema).
        analysis_id:  Required for 'memo_scoped', None for
                       'portfolio_wide' (already validated by the
                       request schema's cross-field check).
        title:        Optional display title.

    Returns:
        The newly-created ``ChatSession`` ORM instance with its
        server-generated UUID and timestamps populated.

    Raises:
        AnalysisNotFoundError: ``session_type='memo_scoped'`` and
            ``analysis_id`` does not exist, or belongs to a different
            user.
        AnalysisNotReadyError: ``session_type='memo_scoped'`` and
            ``analysis_id`` is real and owned by ``user_id``, but its
            ``status`` is not yet 'completed'.
    """
    if session_type == "memo_scoped":
        # analysis_id is guaranteed non-None here by the request
        # schema's own model_validator -- this assertion documents
        # that invariant for readers of this function in isolation
        # (e.g. from a future non-HTTP caller) without re-deriving it.
        assert analysis_id is not None, "memo_scoped session requires analysis_id"

        status_result = await get_analysis_status(
            session, job_id=analysis_id, user_id=user_id
        )
        if status_result is None:
            logger.info(
                "create_chat_session: analysis_id=%s not found or not "
                "owned by user_id=%s",
                analysis_id,
                user_id,
            )
            raise AnalysisNotFoundError(analysis_id)

        if status_result.status != "completed":
            logger.info(
                "create_chat_session: analysis_id=%s not ready (status=%s)",
                analysis_id,
                status_result.status,
            )
            raise AnalysisNotReadyError(status=status_result.status)

    chat_session = ChatSession(
        user_id=user_id,
        analysis_id=analysis_id,
        session_type=session_type,
        title=title,
    )
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)

    logger.info(
        "create_chat_session: created session_id=%s user_id=%s type=%s "
        "analysis_id=%s",
        chat_session.id,
        user_id,
        session_type,
        analysis_id,
    )
    return chat_session


# ---------------------------------------------------------------------------
# list_chat_sessions (GET /api/v1/chat/sessions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatSessionSummary:
    """One row of GET /api/v1/chat/sessions's paginated result."""

    id: uuid.UUID
    session_type: str
    analysis_id: Optional[uuid.UUID]
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ChatSessionPage:
    """
    A single page of ``ChatSessionSummary`` rows plus pagination
    metadata -- same shape as ``backend.services.analysis.HistoryPage``
    and ``backend.services.accuracy_tracker.AccuracyHistoryPage``.
    """

    items: list[ChatSessionSummary]
    total_count: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """True when at least one further row exists beyond this page."""
        return self.offset + len(self.items) < self.total_count


async def list_chat_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int = DEFAULT_SESSIONS_PAGE_SIZE,
    offset: int = 0,
) -> ChatSessionPage:
    """
    Read one page of the caller's own chat sessions, most recently
    updated first.

    Two queries (a COUNT and the page itself), matching
    ``get_analysis_history``'s own documented rationale: this endpoint
    is read at human-interaction frequency, not a hot loop, so a
    second round trip's latency is immaterial next to the clarity of
    two independently-readable statements over one window-function
    query.

    Args:
        session: Active AsyncSession for this request.
        user_id: UUID of the authenticated requester -- every row
                 returned belongs to this user; there is no cross-user
                 session listing endpoint.
        limit:   Page size, already clamped to
                 [1, MAX_SESSIONS_PAGE_SIZE] by the router's
                 ``Query(ge=1, le=MAX_SESSIONS_PAGE_SIZE)`` validation.
        offset:  Rows to skip, already clamped to >= 0 by the same
                 validation.

    Returns:
        A ChatSessionPage with up to ``limit`` ChatSessionSummary rows
        and the total count of the user's sessions.
    """
    count_result = await session.execute(
        select(func.count(ChatSession.id)).where(ChatSession.user_id == user_id)
    )
    total_count = int(count_result.scalar_one())

    page_result = await session.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(page_result.scalars().all())

    items = [
        ChatSessionSummary(
            id=row.id,
            session_type=row.session_type,
            analysis_id=row.analysis_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    return ChatSessionPage(
        items=items, total_count=total_count, limit=limit, offset=offset
    )


# ---------------------------------------------------------------------------
# get_chat_session_messages (GET /api/v1/chat/sessions/{session_id}/messages)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessageEntry:
    """One row of GET .../messages's paginated result."""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    tool_calls: Optional[dict[str, Any]]
    tool_name: Optional[str]
    tokens_used: Optional[int]
    created_at: datetime


@dataclass(frozen=True)
class ChatMessagesPage:
    """
    A single page of ``ChatMessageEntry`` rows, in transcript order
    (oldest first), plus pagination metadata.
    """

    session_id: uuid.UUID
    items: list[ChatMessageEntry]
    total_count: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """True when at least one further row exists beyond this page."""
        return self.offset + len(self.items) < self.total_count


async def get_chat_session_messages(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    limit: int = DEFAULT_MESSAGES_PAGE_SIZE,
    offset: int = 0,
) -> Optional[ChatMessagesPage]:
    """
    Read one page of a chat session's messages, oldest first
    (transcript order).

    Returns None both when no ``chat_sessions`` row exists for
    ``session_id`` AND when a row exists but belongs to a different
    user -- identical not-found semantics to
    ``backend.services.analysis.get_analysis_status``, for the
    identical reason (never reveal a session_id's validity to a
    non-owner). Ordered oldest-first (unlike every other paginated
    endpoint in this codebase, which orders newest-first) because a
    chat transcript only reads correctly in the order the conversation
    actually happened.

    Args:
        session:    Active AsyncSession for this request.
        user_id:    UUID of the authenticated requester.
        session_id: UUID path parameter identifying the chat session.
        limit:      Page size, already clamped to
                    [1, MAX_MESSAGES_PAGE_SIZE] by the router's
                    ``Query(ge=1, le=MAX_MESSAGES_PAGE_SIZE)``
                    validation.
        offset:     Rows to skip, already clamped to >= 0 by the same
                    validation.

    Returns:
        A ChatMessagesPage when session_id exists and belongs to
        user_id (with an empty ``items`` list, not an error, for a
        brand-new session with zero messages so far), or None when
        session_id does not exist or belongs to a different user.
    """
    owner_result = await session.execute(
        select(ChatSession.user_id).where(ChatSession.id == session_id)
    )
    owner_row = owner_result.scalar_one_or_none()

    if owner_row is None:
        logger.debug(
            "get_chat_session_messages: no chat_sessions row for session_id=%s",
            session_id,
        )
        return None

    if uuid.UUID(str(owner_row)) != user_id:
        logger.warning(
            "get_chat_session_messages: session_id=%s belongs to a "
            "different user -- returning not-found to requester",
            session_id,
        )
        return None

    count_result = await session.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    total_count = int(count_result.scalar_one())

    page_result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(page_result.scalars().all())

    items = [
        ChatMessageEntry(
            id=row.id,
            session_id=row.session_id,
            role=row.role,
            content=row.content,
            tool_calls=row.tool_calls,
            tool_name=row.tool_name,
            tokens_used=row.tokens_used,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return ChatMessagesPage(
        session_id=session_id,
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )
