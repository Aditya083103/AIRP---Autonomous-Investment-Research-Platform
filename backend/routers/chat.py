# backend/routers/chat.py
"""
AIRP -- Chat Session REST Endpoints (T-103)

POST /api/v1/chat/sessions                          (create a session)
GET  /api/v1/chat/sessions                           (list my sessions)
GET  /api/v1/chat/sessions/{session_id}/messages     (list a session's messages)

T-103 acceptance criteria (from task spec):
  * All endpoints covered by pytest with the existing autouse
    pipeline-mocking fixture pattern
  * JWT-protected per existing auth pattern

HTTP-layer concerns only (request validation via Pydantic schemas,
authentication via ``get_current_user``, translating service-layer
results into the response schema) -- all database reads/writes and
ownership/readiness validation live in
``backend.services.chat_session_service``, mirroring the auth
router/service split established in T-046 and followed by every
router since (``analysis.py``, ``documents.py``, ``accuracy.py``).

Why "/api/v1/chat", not the bare "/chat" the task description's
shorthand uses
------------------------------------------------------------------------
Every router in this codebase other than ``auth.py`` (which predates
the ``/api/v1`` convention and is left as-is rather than introducing a
breaking path change to already-shipped auth endpoints) is mounted
under ``/api/v1/<feature>`` -- ``/api/v1/analysis``,
``/api/v1/documents``, ``/api/v1/accuracy``. T-103's task description
("POST /chat/sessions, GET /chat/sessions, ...") is the same kind of
shorthand every other Phase 10 task doc has already used for its own
endpoints (T-104's own spec says "WS /api/v1/chat/{session_id}/stream"
-- WITH the prefix -- confirming "/chat" elsewhere in Phase 10's task
docs is shorthand, not a deliberate deviation). This router uses
``/api/v1/chat`` for consistency with every other feature router, and
so T-104's WebSocket endpoint (which the task spec already writes with
the full prefix) lands under the same path family.

Why JWT auth (``get_current_user``), not the service-token auth
``accuracy.py`` uses
------------------------------------------------------------------------
``verify_service_token`` (T-090) exists specifically for the one
machine-to-machine caller in this codebase that has no ``User`` row to
represent it (the scheduled GitHub Actions evaluation workflow calling
``POST /api/v1/accuracy/run``). Every chat session belongs to exactly
one human user by definition (``chat_sessions.user_id``, T-099) -- the
same ``get_current_user`` JWT dependency every other user-facing
endpoint in this codebase already uses (``analysis.py``,
``documents.py``) is the correct and only fit here, and is what T-103's
own acceptance criterion ("JWT-protected per existing auth pattern")
asks for by name.

Why POST returns 201, not 202 like ``POST /api/v1/analysis/start``
------------------------------------------------------------------------
``POST /api/v1/analysis/start`` returns 202 Accepted because it
schedules a background task (the LangGraph pipeline) that has not run
yet when the response is sent -- the created ``analyses`` row is not
yet the "final" resource the caller asked for. Creating a chat session
has no such asynchronous follow-up: the ``ChatSession`` row this
endpoint returns IS the complete, final resource the instant the
response is sent (T-104's WebSocket streaming, a separate task, is
what a caller opens next to actually converse in it). 201 Created is
the correct status for a synchronous resource creation that completes
within the request, per RFC 9110.

Why memo-scoped validation errors map to 404/409, matching
``GET /api/v1/analysis/{job_id}/result``'s own status codes
------------------------------------------------------------------------
See ``backend.services.chat_session_service``'s own module docstring --
``AnalysisNotFoundError``/``AnalysisNotReadyError`` are deliberately
the same 404-vs-409 split ``backend/routers/analysis.py`` already uses
for "job_id does not exist or is not yours" vs. "job_id is real and
yours, but not finished yet", reused here rather than reinvented.

Design decisions
------------------------------------------------------------------------
* No ``from __future__ import annotations`` -- matches every other
  router in this codebase (none of them use it).
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.models.orm import User
from backend.models.schemas import (
    ChatMessageResponse,
    ChatMessagesResponse,
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatSessionResponse,
)
from backend.services.chat_session_service import (
    DEFAULT_MESSAGES_PAGE_SIZE,
    DEFAULT_SESSIONS_PAGE_SIZE,
    MAX_MESSAGES_PAGE_SIZE,
    MAX_SESSIONS_PAGE_SIZE,
    AnalysisNotFoundError,
    AnalysisNotReadyError,
    create_chat_session,
    get_chat_session_messages,
    list_chat_sessions,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /api/v1/chat/sessions
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new AIRP Assistant chat session",
    description=(
        "Creates a chat session for the authenticated user -- either "
        "'memo_scoped' (tied to one completed analysis, for asking "
        "about that specific memo) or 'portfolio_wide' (for questions "
        "spanning the user's whole analysis history). For "
        "'memo_scoped', analysis_id must reference a completed "
        "analysis the caller owns: returns 404 if it does not exist "
        "or belongs to a different user, and 409 if it exists but has "
        "not finished yet."
    ),
)
async def create_chat_session_endpoint(
    body: ChatSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ChatSessionResponse:
    try:
        chat_session = await create_chat_session(
            session,
            user_id=current_user.id,
            session_type=body.session_type,
            analysis_id=body.analysis_id,
            title=body.title,
        )
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No analysis found for analysis_id={body.analysis_id} "
                "(or it belongs to a different user)"
            ),
        ) from exc
    except AnalysisNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"analysis_id={body.analysis_id} is not ready yet "
                f"(status='{exc.status}'). A memo-scoped chat session "
                "can only be created once the analysis has completed."
            ),
        ) from exc

    return ChatSessionResponse(
        id=chat_session.id,
        session_type=chat_session.session_type,
        analysis_id=chat_session.analysis_id,
        title=chat_session.title,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List the caller's own chat sessions, most recently updated first",
    description=(
        "Returns one page of the authenticated user's own chat "
        "sessions (both memo-scoped and portfolio-wide), ordered by "
        "updated_at descending. Defaults to the most recent 20 "
        "(DEFAULT_SESSIONS_PAGE_SIZE); pass limit/offset to page "
        "further. Never returns another user's sessions."
    ),
)
async def list_chat_sessions_endpoint(
    limit: int = Query(
        default=DEFAULT_SESSIONS_PAGE_SIZE,
        ge=1,
        le=MAX_SESSIONS_PAGE_SIZE,
        description="Maximum number of sessions to return on this page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of most-recently-updated sessions to skip",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ChatSessionListResponse:
    page = await list_chat_sessions(
        session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    return ChatSessionListResponse(
        items=[
            ChatSessionResponse(
                id=entry.id,
                session_type=entry.session_type,
                analysis_id=entry.analysis_id,
                title=entry.title,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )
            for entry in page.items
        ],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/chat/sessions/{session_id}/messages
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatMessagesResponse,
    status_code=status.HTTP_200_OK,
    summary="List one chat session's messages, oldest first",
    description=(
        "Returns one page of session_id's messages in transcript "
        "order (oldest first) -- unlike every other paginated list "
        "endpoint in this API, which orders newest-first. Defaults to "
        "the most recent 50 (DEFAULT_MESSAGES_PAGE_SIZE) after any "
        "offset; pass limit/offset to page further. Returns 404 if "
        "session_id does not exist or belongs to a different user."
    ),
)
async def get_chat_session_messages_endpoint(
    session_id: uuid.UUID,
    limit: int = Query(
        default=DEFAULT_MESSAGES_PAGE_SIZE,
        ge=1,
        le=MAX_MESSAGES_PAGE_SIZE,
        description="Maximum number of messages to return on this page",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of oldest messages to skip before this page",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ChatMessagesResponse:
    page = await get_chat_session_messages(
        session,
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )

    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chat session found for the given session_id",
        )

    return ChatMessagesResponse(
        session_id=page.session_id,
        items=[
            ChatMessageResponse(
                id=entry.id,
                session_id=entry.session_id,
                role=entry.role,
                content=entry.content,
                tool_calls=entry.tool_calls,
                tool_name=entry.tool_name,
                tokens_used=entry.tokens_used,
                created_at=entry.created_at,
            )
            for entry in page.items
        ],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )
