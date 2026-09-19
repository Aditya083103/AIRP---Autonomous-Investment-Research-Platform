# backend/routers/chat_stream.py
"""
AIRP -- AIRP Assistant WebSocket Token Streaming (T-104)

WS /api/v1/chat/{session_id}/stream

T-104 acceptance criteria (from task spec):
  * Client receives incremental tokens
  * Connection closes cleanly on completion
  * Reconnect handled gracefully

What this endpoint does
------------------------
Lets a client hold one persistent connection to a chat session
(T-099's schema, T-103's REST endpoints for creating/listing sessions
and reading transcript history) and exchange multiple turns over it:
the client sends ``{"message": "<text>"}``, the server streams the
AIRP Assistant's reply back token by token as T-102's guardrailed
``chat_llm.astream_chat`` produces them, persists both sides of the
turn to ``chat_messages`` (T-103's schema), and waits for the next
message -- all without closing the socket between turns. On connect:

  1. Authenticates the caller via a ``token`` query parameter (a
     bearer JWT), the same mechanism T-049's
     ``backend/routers/websocket.py`` already established for
     WebSocket routes, for the identical reason (browsers cannot set
     custom headers on a WebSocket handshake).
  2. Confirms ``session_id`` exists and belongs to the authenticated
     user via ``backend.services.chat_session_service.
     get_chat_session_stream_info`` -- closes with code 4404
     immediately if not, mirroring T-049's identical closing code for
     the identical "not found or not yours" condition on the analysis
     progress stream.
  3. Enters a receive loop: for each incoming ``{"message": ...}``, it
     streams one full AIRP Assistant reply back (see "Per-turn
     streaming loop" below), then waits for the next message on the
     SAME connection. The connection only ends when the client
     disconnects, or a truly fatal per-connection condition occurs
     (never on a single bad message or a single failed generation --
     see "Why a bad turn does not close the connection" below).

Why this router does NOT reuse ``backend.services.ws_broadcaster``'s
actual ``subscribe``/``unsubscribe``/``publish_event`` functions
------------------------------------------------------------------------
``ws_broadcaster.py``'s entire pub/sub registry exists to solve one
specific problem: ``backend.services.analysis.run_analysis_pipeline``
executes the LangGraph pipeline on a worker thread (via
``asyncio.to_thread``), so node-completion events need to cross an OS
thread boundary to reach a WebSocket connection living on FastAPI's
main event loop -- that module's own docstring documents exactly why a
``threading.Lock`` + ``call_soon_threadsafe`` registry is the correct
tool for that. The AIRP Assistant's streaming call
(``backend.services.chat_llm.astream_chat``) is different in kind: it
is an ``async def`` generator awaited directly on the SAME coroutine
that is already handling this WebSocket connection -- there is no
worker thread to bridge back from, no other subscriber that could ever
want the same token stream (unlike an analysis job, which any number
of open browser tabs might be watching), and therefore nothing for a
cross-thread pub/sub registry to actually solve here. Forcing chat
tokens through that registry would add exactly the indirection its own
docstring says exists to avoid when it is not needed.

What IS reused from the T-049 WebSocket pattern (faithfully, not just
in spirit)
------------------------------------------------------------------------
* Query-param JWT auth, duplicated locally as ``_authenticate`` rather
  than imported from ``backend.routers.websocket`` -- a small,
  self-contained ~15-line function, and this codebase's established
  precedent (e.g. ``backend.tools.portfolio_tools``'s own
  ``_parse_decision``, duplicated from ``chat_service.py``/
  ``analysis.py`` for the identical stated reason) is that a caller
  only needing a few lines of shared logic keeps its own copy rather
  than importing a private helper across router modules -- especially
  here, where importing FROM ``backend.routers.websocket`` would also
  be the only cross-router import in the whole ``backend/routers/``
  package, and where leaving T-049's already-shipped, already-tested
  file completely untouched is itself a real "don't put previously
  passing CI at risk" property.
* Application-specific close codes in the SAME 4000-4999 numeric
  range, reusing the SAME numbers T-049 already established for the
  same meanings (4401 unauthorized, 4404 not found) -- a client
  handling both this stream and the analysis progress stream can share
  one close-code interpretation table across both.
* The poll/heartbeat/disconnect-probe SHAPE of T-049's
  ``_forward_live_events`` (``asyncio.wait(..., timeout=...)`` around
  the next item -- NOT ``wait_for``, which cancels on timeout and was
  the actual bug in both routers' original disconnect probes, see
  ``_InboundReader``'s docstring -- plus a heartbeat after N
  consecutive timeouts, and a single persistent ``receive()`` task to
  detect a dead TCP connection between real events) -- applied here to
  ``astream_chat``'s own async iterator instead of a broadcaster queue,
  since (per the point above) there is no queue in this design, only
  the LLM's own token stream to poll the same way.
* The same "accept the connection, then close with an explicit
  application code" strategy (rather than denying the handshake) for
  the same reason T-049's docstring gives: the browser WebSocket API
  exposes almost nothing about why a handshake was denied, but exposes
  the close code once the connection opened and was then closed.

Why a bad turn (malformed client message, or a failed LLM call) does
NOT close the connection
------------------------------------------------------------------------
This is the concrete mechanism behind "reconnect handled gracefully":
a client should not need to reconnect just to recover from one bad
message or one failed generation. A malformed/oversized/empty
``message`` payload gets an ``event_type="error"`` event over the SAME
socket and the receive loop simply continues waiting for the next
message. A ``ChatLLMError`` from ``astream_chat`` (the underlying
provider erroring or timing out) gets the same treatment -- an error
event, then back to waiting -- rather than tearing the whole
connection down over one failed generation. The connection only closes
when the client itself disconnects (the normal case), or -- deliberately, the one
unrecoverable case -- when a mid-stream disconnect is detected (see
below), since there is no client left to keep serving.

Why reconnecting after ANY disconnect (mid-turn or between turns) just
works, with no special server-side reconnect handling
------------------------------------------------------------------------
This server keeps no in-memory, connection-scoped conversation state
at all -- every message, on both sides of every turn, is persisted to
``chat_messages`` (via ``append_chat_message``) as it happens, and each
new connection independently re-authenticates, re-validates ownership,
and re-reads the full transcript from the database (the same
``get_chat_session_messages`` T-103's REST endpoint already uses) to
reconstruct conversation context. A client that disconnects for ANY
reason -- a dropped WiFi connection, a laptop going to sleep, a tab
being closed and reopened -- can simply open a brand-new WebSocket
connection at any later time and it behaves identically to a first
connection: same auth, same ownership check, same history load. There
is no server-side "resume this exact connection" protocol to implement
or to get wrong, because there is no server-side state a reconnect
would need to resume.

The ONE case worth engineering deliberately: a client that disconnects
WHILE a reply is still streaming. Rather than silently discarding
whatever the model had already generated, the partial text collected
so far is persisted as a ``ChatMessage`` (content prefixed with a
clear ``[response interrupted -- connection lost]`` marker) before the
handler returns -- so a reconnecting client's next
``GET /api/v1/chat/sessions/{id}/messages`` call (or the history this
same WS route loads on reconnect) shows the user what the assistant
had said so far, instead of that generation vanishing without a trace.

Why response_style is now read from ``user_preferences.chat_response_style``
(as of T-106), after being hard-coded to "concise" through T-104/T-105
------------------------------------------------------------------------
T-099's schema always had this column, and ``backend.services.
chat_llm.build_system_prompt`` always accepted a ``response_style``
argument -- T-104's own docstring called wiring an actual per-user
lookup here a "small, natural, and DELIBERATELY DEFERRED follow-up,
not an oversight", specifically because T-104's acceptance criteria
were entirely about the WebSocket streaming mechanics, not preference
plumbing. T-106 -- literally titled "Personalization via
user_preferences" -- is that deferred follow-up: this router now loads
the caller's ``UserPreferences`` row once per turn via
``apply_extracted_preferences`` (which lazily creates the row via
``get_or_create_user_preferences`` if this is the caller's very first
chat turn ever -- see ``preference_service.py``) and passes its actual
``chat_response_style`` to ``astream_chat``. A brand-new row's
``chat_response_style`` is simply T-099's own column default
(``server_default="concise"``) -- this router no longer keeps its own
separate hard-coded constant for it; the one former hard-coded
constant this module used through T-104/T-105 has been removed rather
than left around unused.

Personalization (T-106): risk appetite and preferred sectors
------------------------------------------------------------------------
Two NEW ``user_preferences`` columns (T-106's migration, on top of
T-099's table): ``risk_appetite`` and ``preferred_sectors``, both NULL
/empty until the AIRP Assistant has asked and the user has answered
once (``backend.services.chat_llm.build_personalization_instruction``
carries the actual "ask, at most once" instruction text; this router
only loads and persists the data, it contains no wording of its own).
Each turn:

  1. ``get_or_create_user_preferences`` loads (or lazily creates) the
     caller's preferences row -- the same row ``chat_response_style``
     above is read from.
  2. ``extract_preferences`` (``backend.services.
     preference_extractor``) runs a deterministic, keyword-based check
     of the user's OWN just-sent message for a stated risk appetite
     and/or preferred sectors -- see that module's own docstring for
     why this is intentionally NOT a second LLM call.
  3. ``apply_extracted_preferences`` persists anything newly
     recognised, but ONLY into a field that is still unset --
     see ``backend.services.preference_service``'s own docstring for
     why an already-known preference is never silently overwritten by
     a later, more casual mention.
  4. The (possibly just-updated) ``risk_appetite``/``preferred_sectors``
     are passed to ``astream_chat``, which threads them into
     ``build_system_prompt`` -- see ``chat_llm.py``'s own docstring for
     why that is a separate, independently testable instruction block
     rather than folded into the guardrail itself.

This entire flow reads and writes ONLY ``user_preferences`` -- it never
touches ``analyses``, ``investment_memos``, or any other
verdict-bearing table, and ``backend/agents/portfolio_manager.py`` (the
only code that ever produces a BUY/HOLD/SELL verdict) has no
preferences argument and is not imported anywhere in this router or in
the personalization modules it calls -- the concrete, checkable basis
for this task's "verdicts remain byte-identical regardless of
preferences" acceptance criterion.

Why a memo-scoped session's grounded context is loaded once per turn,
not cached for the connection's lifetime
------------------------------------------------------------------------
Unlike T-049's analysis-progress stream (which opens exactly one
narrow, short-lived DB session up front and needs no further database
access for the rest of the connection), a chat connection needs the
database on EVERY turn -- to persist both sides of the exchange and to
re-read the latest transcript for context. There is nothing to gain
from holding one pooled connection open for a whole multi-turn chat
session (which could span many minutes of a user thinking between
messages) the way T-049 avoids doing for its own ~90-second pipeline
stream; each turn instead opens its OWN narrow ``AsyncSessionLocal()``
block, used only for that turn's DB work, then closes again before
streaming begins -- the identical "don't hold a pooled connection open
longer than the work actually in flight" principle T-049 already
documents, applied at per-turn granularity instead of
per-connection granularity because chat's database need recurs every
turn rather than being front-loaded once.

Portfolio-wide tool-calling (B9)
------------------------------------------------------------------------
T-101 built three portfolio-wide LangChain tools
(``backend.tools.portfolio_tools.build_portfolio_tools``) that this
router did not originally bind to the streaming LLM call -- a
``session_type='portfolio_wide'`` connection worked end-to-end for the
guardrail persona and streaming mechanics, but could not answer a
question requiring a look-up of the user's OWN other analyses or
uploaded documents. ``_build_chat_tools`` (B9, below) closes that gap:
every turn now runs a non-streamed tool-calling decision round
(``backend.services.chat_llm.run_tool_calling_round``) BEFORE
streaming begins -- see ``_build_chat_tools``'s and ``_run_one_turn``'s
own docstrings for the full design (why the round runs inside this
turn's own DB session block, how a tool-round failure surfaces as an
error event, and why this is a decide-then-stream split rather than
interleaving tool-call events with token events mid-stream).

Why 'start' now carries the user message's id (B9 edit-and-resend)
------------------------------------------------------------------------
``backend.routers.chat`` (T-103) grew a
``DELETE /api/v1/chat/sessions/{id}/messages/{message_id}`` endpoint
(B9) that truncates a session from one message onward -- the
server-side half of "edit a past message, matching the Claude UX":
the client deletes the edited message and everything the assistant
said after it, then simply calls this same streaming endpoint again
with the edited text, which appends a fresh user turn and generates a
new reply exactly like any other message. That truncate endpoint is
addressed BY MESSAGE ID, but this router previously never told the
client what id its own just-sent user message got -- only an assistant
reply's id (on 'done') was ever surfaced. A user message sent over a
live connection therefore had no known server id to later pass to the
truncate endpoint if the person wanted to edit it, unlike a message
loaded from ``GET .../messages`` (T-103), which always carries its
real id. Piggybacking the just-persisted user message's id onto the
'start' event (sent immediately after that persist, before generation
even begins) closes that gap with no new event type and no change to
this loop's shape -- see ``ChatStreamEvent``'s own docstring above.

Design decisions
------------------------------------------------------------------------
* No ``from __future__ import annotations`` -- matches every other
  router in this codebase.
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
"""

import asyncio
from collections.abc import MutableMapping
import json
import logging
from typing import Any, AsyncIterator, Optional, TypedDict
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import AsyncSessionLocal
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.services.analysis import AnalysisNotReadyError
from backend.services.auth import InvalidTokenError, decode_access_token
from backend.services.chat_cache import (
    PORTFOLIO_SCOPE,
    build_cache_key,
    get_cached_reply,
    set_cached_reply,
)
from backend.services.chat_llm import (
    ChatLLMError,
    astream_chat_from_messages,
    build_chat_messages,
    get_chat_llm,
    get_chat_llm_fallback,
    run_tool_calling_round,
)
from backend.services.chat_service import build_memo_context
from backend.services.chat_session_service import (
    MAX_MESSAGES_PAGE_SIZE,
    ChatSessionStreamInfo,
    append_chat_message,
    get_chat_session_messages,
    get_chat_session_stream_info,
)
from backend.services.preference_extractor import extract_preferences
from backend.services.preference_service import apply_extracted_preferences
from backend.tools.portfolio_tools import build_portfolio_tools
from backend.tools.ratios import fetch_ratios
from backend.tools.stock_price import fetch_stock_price

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# ---------------------------------------------------------------------------
# Close codes -- same numeric meanings as backend/routers/websocket.py
# (T-049), intentionally kept in sync rather than imported (see module
# docstring for why this is a deliberate, documented duplication).
# ---------------------------------------------------------------------------

_CLOSE_UNAUTHORIZED = 4401
_CLOSE_NOT_FOUND = 4404

# ---------------------------------------------------------------------------
# Streaming tuning constants
# ---------------------------------------------------------------------------

#: How long the token-forwarding loop waits on the next chunk from
#: astream_chat before polling for a client-initiated disconnect.
#: Same value and rationale as T-049's own
#: _QUEUE_POLL_INTERVAL_SECONDS.
_TOKEN_POLL_INTERVAL_SECONDS = 2.0

#: Consecutive poll-interval timeouts (i.e. seconds of no new token,
#: at _TOKEN_POLL_INTERVAL_SECONDS each) before a heartbeat event is
#: sent. Same value and rationale as T-049's own
#: _HEARTBEAT_AFTER_TICKS -- keeps the socket from looking silent long
#: enough for a router/proxy/browser idle timeout to drop it while the
#: provider is still working on the first (or a slow) token.
_HEARTBEAT_AFTER_TICKS = 5

#: Hard cap on one incoming user message's length. Generous enough for
#: any realistic chat question, small enough that one malformed/abusive
#: client message cannot balloon the prompt sent to the LLM or the row
#: written to chat_messages.content.
_MAX_USER_MESSAGE_LENGTH = 4000

#: Prefix written to chat_messages.content when a generation is cut
#: short by a mid-stream client disconnect -- see "Why reconnecting...
#: just works" in the module docstring.
_INTERRUPTED_PREFIX = "[response interrupted -- connection lost]\n\n"


# ---------------------------------------------------------------------------
# Outgoing event shape
# ---------------------------------------------------------------------------


class ChatStreamEvent(TypedDict):
    """
    One push payload sent over WS /api/v1/chat/{session_id}/stream.

    ``event_type``:
      'start'     -- a new assistant reply has begun generating (sent
                      once per turn, before the first token).
                      ``message_id`` (B9) is the id of the USER
                      message this turn just persisted -- see the
                      module docstring's "Why 'start' now carries the
                      user message's id" section. This is the ONLY
                      event in this turn that ever carries a user
                      message's id; every other non-null
                      ``message_id`` in this protocol (below) is an
                      assistant message's.
      'token'     -- one incremental chunk of the assistant's reply.
      'heartbeat' -- no new token in a while; keeps the connection
                      alive during a slow first-token wait. Carries no
                      new content (token == "").
      'done'      -- the reply finished successfully. ``message_id``
                      is the persisted assistant ChatMessage's id.
      'error'     -- the turn failed (bad client input, or the LLM
                      call itself failed). The connection stays open;
                      the client may send another message.

    ``analysis_job_id`` (FEATURE 1): set ONLY on the 'start' event of a
    turn whose tool-calling round successfully called
    ``backend.tools.portfolio_tools``'s ``request_new_analysis`` (see
    ``_extract_started_analysis_job_id`` below) -- every other event,
    and every turn that did not start a new analysis, carries ``None``.
    The frontend (``useChatStream``/``ChatWidget``) uses this to
    navigate to the existing live-progress route for that job_id --
    reusing ``AnalysisResultPage`` (``/analysis/:jobId/result``), never
    building a second progress UI inside the chat panel.
    """

    session_id: str
    event_type: str
    token: str
    message_id: Optional[str]
    is_final: bool
    error: Optional[str]
    analysis_job_id: Optional[str]


def _cast_stream_event(  # nosec B107 -- "token" is a stream chunk, not a password
    session_id: uuid.UUID,
    event_type: str,
    token: str = "",
    message_id: Optional[uuid.UUID] = None,
    is_final: bool = False,
    error: Optional[str] = None,
    analysis_job_id: Optional[str] = None,
) -> ChatStreamEvent:
    return ChatStreamEvent(
        session_id=str(session_id),
        event_type=event_type,
        token=token,
        message_id=str(message_id) if message_id is not None else None,
        is_final=is_final,
        error=error,
        analysis_job_id=analysis_job_id,
    )


# ---------------------------------------------------------------------------
# Auth -- query-param token (duplicated from backend.routers.websocket;
# see module docstring for why)
# ---------------------------------------------------------------------------


async def _authenticate(
    token: str, session: AsyncSession, settings: Settings
) -> Optional[User]:
    """
    Resolve a query-param bearer token to a User row, or None.

    Mirrors backend.dependencies.auth.get_current_user's verification
    logic, including the B6 token_version check -- a token issued
    before a password reset must not open a chat WS connection either,
    the same as it can no longer authenticate any REST endpoint.
    """
    try:
        payload = decode_access_token(token, settings=settings)
    except InvalidTokenError:
        return None

    try:
        user_id = uuid.UUID(payload.sub)
    except (AttributeError, ValueError):
        return None

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if payload.token_version != user.token_version:
        return None
    return user


# ---------------------------------------------------------------------------
# Incoming message validation
# ---------------------------------------------------------------------------


def _extract_user_message(payload: Any) -> tuple[Optional[str], Optional[str]]:
    """
    Validate one incoming client payload.

    Returns:
        (message, None) on success, or (None, error_message) when the
        payload is not a well-formed {"message": "<non-empty text>"}
        object -- the router sends `error_message` back as an
        ``event_type="error"`` event rather than closing the
        connection.
    """
    if not isinstance(payload, dict):
        return None, "expected a JSON object with a 'message' field"

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return None, "'message' must be a non-empty string"

    if len(message) > _MAX_USER_MESSAGE_LENGTH:
        return None, f"'message' must be at most {_MAX_USER_MESSAGE_LENGTH} characters"

    return message, None


# ---------------------------------------------------------------------------
# Inbound message reader -- ONE persistent, never-mid-flight-cancelled
# receive() for the whole connection (BUGFIX, see class docstring)
# ---------------------------------------------------------------------------


class _InboundReader:
    """
    Single, persistent, non-destructively-polled consumer of this
    connection's incoming messages.

    Shared across the whole connection lifetime -- both the per-turn
    message reads in ``_turn_loop`` AND the mid-stream disconnect probe
    in ``_run_one_turn`` -- so there is never more than one
    ``websocket.receive()`` call in flight at a time.

    BUGFIX (root cause of the "AIRP Assistant failed to generate a
    response" / connection dying mid-reply reports): the previous
    ``_client_still_connected`` helper called
    ``asyncio.wait_for(websocket.receive(), timeout=0.01)`` fresh on
    EVERY idle poll tick while waiting for the next LLM token,
    cancelling the underlying ``receive()`` call the instant it timed
    out -- which, since the client never sends anything mid-reply, was
    every single tick. Starlette/uvicorn's ``receive()`` is a
    resumable, stateful awaitable -- the exact same kind of object an
    async generator's ``__anext__()`` is, and this module's own
    ``_run_one_turn`` already documents (for ``token_iter.__anext__()``)
    that cancelling such a call mid-flight destroys its paused state.
    The identical lesson applies to ``receive()``: repeatedly
    cancelling it corrupts the connection's receive state badly enough
    that the connection dies from under a still-healthy request --
    observed as an abnormal closure (WebSocket close code 1006) as
    soon as a single token took longer than
    ``_TOKEN_POLL_INTERVAL_SECONDS`` to arrive, which is the realistic
    case for any real LLM provider, not the exception. This class
    instead keeps exactly one ``receive()`` call in flight for the
    connection's entire lifetime and is polled via
    ``asyncio.wait({reader.task, ...}, timeout=...)`` (which never
    cancels on timeout) -- ``reader.task`` itself is only ever awaited
    inside such a ``asyncio.wait(...)`` call, never cancelled, except
    once in ``close()`` when the connection is already being torn down
    for good.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        # T-074 audit finding (mypy warn_unused_ignores pass, C15):
        # WebSocket.receive() is typed to return starlette.types.Message,
        # which IS MutableMapping[str, Any], not dict[str, Any] -- the
        # annotation below now matches that exactly instead of narrowing
        # it to dict, which is what made asyncio.ensure_future's inferred
        # Awaitable[dict[str, Any]] mismatch the coroutine's real type.
        self.task: "asyncio.Task[MutableMapping[str, Any]]" = asyncio.ensure_future(
            websocket.receive()
        )

    def advance(self) -> MutableMapping[str, Any]:
        """
        Consume the just-completed message and start listening for the
        next one. Only valid to call once ``self.task.done()`` is True
        (i.e. after it has appeared in an ``asyncio.wait(...)`` result).
        """
        message = self.task.result()
        self.task = asyncio.ensure_future(self._websocket.receive())
        return message

    def close(self) -> None:
        """Final teardown only -- cancels the in-flight receive for good."""
        if not self.task.done():
            self.task.cancel()


# ---------------------------------------------------------------------------
# WS /api/v1/chat/{session_id}/stream
# ---------------------------------------------------------------------------


@router.websocket("/{session_id}/stream")
async def stream_chat(
    websocket: WebSocket,
    session_id: uuid.UUID,
    settings: Settings = Depends(get_settings_dependency),
) -> None:
    """
    Stream AIRP Assistant replies for one chat session, turn by turn.

    See the module docstring for the full connect/auth/loop/close
    sequence and the reasoning behind every design choice below. This
    handler never lets an exception escape unhandled -- every failure
    path either sends an ``event_type="error"`` event and keeps
    listening, or closes the socket with an explicit code.
    """
    token = websocket.query_params.get("token", "")

    await websocket.accept()

    async with AsyncSessionLocal() as auth_session:
        user = await _authenticate(token, auth_session, settings) if token else None
        if user is None:
            await websocket.close(code=_CLOSE_UNAUTHORIZED)
            return

        stream_info = await get_chat_session_stream_info(auth_session, session_id)

    if stream_info is None or stream_info.user_id != user.id:
        # Same non-enumeration rule as every other ownership-scoped
        # endpoint in this codebase: "does not exist" and "exists but
        # is not yours" close with the identical code.
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    reader = _InboundReader(websocket)
    try:
        await _turn_loop(
            websocket, session_id=session_id, user=user, info=stream_info, reader=reader
        )
    finally:
        reader.close()


async def _turn_loop(
    websocket: WebSocket,
    session_id: uuid.UUID,
    user: User,
    info: ChatSessionStreamInfo,
    reader: "_InboundReader",
) -> None:
    """
    Receive client messages and stream one AIRP Assistant reply per
    message, until the client disconnects.

    Extracted from ``stream_chat`` so the connect-time auth/ownership
    checks above stay separate from the (much longer) per-turn
    streaming logic. Reads via ``reader`` (see ``_InboundReader``)
    rather than ``websocket.receive_json()`` directly, so the exact
    same never-cancelled receive task can also be polled from inside
    ``_run_one_turn``'s token-streaming loop without ever having two
    concurrent ``receive()`` calls on the same connection.
    """
    while True:
        try:
            await reader.task
        except WebSocketDisconnect:
            return
        except Exception:
            # Receive-path error that is not a clean disconnect --
            # treat the connection as unusable; nothing left to read.
            return

        try:
            message = reader.advance()
        except WebSocketDisconnect:
            return
        except Exception:
            return

        if message.get("type") == "websocket.disconnect":
            return

        raw_text = message.get("text")
        if raw_text is None:
            # Binary frame or some other unexpected message on a
            # JSON-only protocol -- tell the client and keep listening.
            try:
                await websocket.send_json(
                    _cast_stream_event(
                        session_id,
                        event_type="error",
                        error="expected a text (JSON) message",
                    )
                )
            except Exception:
                return
            continue

        try:
            payload = json.loads(raw_text)
        except Exception:
            # Malformed JSON -- tell the client and keep listening
            # rather than tearing the connection down.
            try:
                await websocket.send_json(
                    _cast_stream_event(
                        session_id,
                        event_type="error",
                        error="could not parse message as JSON",
                    )
                )
            except Exception:
                return
            continue

        user_message, validation_error = _extract_user_message(payload)
        if validation_error is not None:
            try:
                await websocket.send_json(
                    _cast_stream_event(
                        session_id, event_type="error", error=validation_error
                    )
                )
            except Exception:
                return
            continue

        # T-095 audit fix: replaced a bare `assert` (stripped under
        # `python -O`, which would let a None user_message reach
        # _run_one_turn below) with an explicit check. This branch
        # should be unreachable given _extract_user_message's contract
        # (validation_error is None implies user_message is not None),
        # so log it and keep the connection alive rather than crash the
        # whole WebSocket on what would be an internal invariant bug.
        if user_message is None:
            logger.error(
                "chat_stream: _extract_user_message returned no "
                "validation_error but also no user_message for "
                "session_id=%s -- skipping this message",
                session_id,
            )
            continue
        await _run_one_turn(
            websocket,
            session_id=session_id,
            user=user,
            info=info,
            user_message=user_message,
            reader=reader,
        )


def _build_chat_tools(
    session: AsyncSession, user: User, session_type: str
) -> list[BaseTool]:
    """
    Build the LangChain tools available for one chat turn (B9).

    The live-market-data tools (``fetch_ratios``, ``fetch_stock_price``)
    are bound for EVERY session type -- a user asking "what's TCS's P/E
    right now?" is a reasonable question in a memo-scoped conversation
    too, not just a portfolio-wide one. ``backend.tools.portfolio_tools``
    ``'s four tools are ADDITIONALLY bound only for a portfolio-wide
    session -- they read or act on the caller's own analysis history /
    uploaded documents / new-analysis requests, none of which has a
    meaning scoped to one already-open memo.

    Root cause this closes: chat_stream.py's own module docstring used
    to document portfolio-wide tool-calling as a deliberately deferred
    "known scope boundary" -- the guardrail persona and streaming
    mechanics worked, but the assistant had no way to look up the
    user's own analyses, so a portfolio-wide question about a specific
    past analysis produced a false "I don't have that" / "analysis has
    not been done" even when the user genuinely had one.

    Args:
        session:      The turn's own AsyncSession -- portfolio_tools'
                      two DB-backed tools are bound to it via a closure
                      (see build_portfolio_tools's own docstring for why
                      user_id/session are never LLM-fillable tool
                      arguments). Callers MUST run any tool round that
                      uses these tools while this session is still open
                      -- see run_tool_calling_round's own docstring.
        user:         The authenticated chat requester.
        session_type: ``info.session_type`` -- 'memo_scoped' or
                      'portfolio_wide'.

    Returns:
        A list of LangChain tools, never empty (the live-data tools are
        always included).
    """
    tools: list[BaseTool] = [fetch_ratios, fetch_stock_price]
    if session_type == "portfolio_wide":
        tools = build_portfolio_tools(session, user.id) + tools
    return tools


async def _reply_token_source(
    cached_reply: Optional[str],
    immediate_text: Optional[str],
    messages: list[BaseMessage],
    llm: Any,
) -> AsyncIterator[str]:
    """
    Unify the three ways this turn's reply text can become available,
    behind the SAME async-iterator interface the polling loop below
    already expects (so that loop -- with its careful non-cancelling
    disconnect/heartbeat handling -- needs no changes regardless of
    which source produced the reply):

      1. ``cached_reply`` (B9 reply cache hit) -- yielded once, no LLM
         call at all.
      2. ``immediate_text`` (the B9 tool-calling round decided no tool
         was needed and already has the model's complete reply) --
         yielded once, no second LLM call.
      3. Neither: a real token-by-token stream from
         ``astream_chat_from_messages`` (a fresh generation, or the
         follow-up call after a tool round appended results to
         ``messages``).
    """
    if cached_reply is not None:
        yield cached_reply
        return
    if immediate_text is not None:
        yield immediate_text
        return
    async for token in astream_chat_from_messages(messages, llm=llm):
        yield token


class _StreamAlreadyHandled(Exception):
    """
    Internal signal raised by ``_poll_reply_tokens`` when the turn ended
    for a reason that is ALREADY fully handled (a client disconnect, or
    a failed send on an already-broken connection -- any partial reply
    is already persisted by the time this is raised). Distinct from
    ``ChatLLMError`` specifically so ``_run_one_turn`` can tell "the LLM
    failed, a fallback-provider retry might help" apart from "the
    connection is gone, retrying anything is pointless" -- catching
    ``Exception`` broadly at the call site would conflate the two.
    """


async def _poll_reply_tokens(
    websocket: WebSocket,
    reader: "_InboundReader",
    session_id: uuid.UUID,
    cached_reply: Optional[str],
    immediate_text: Optional[str],
    messages: list[BaseMessage],
    llm: Any,
) -> list[str]:
    """
    Run the token-polling loop for ONE LLM client and return the tokens
    collected, sending each as a ``token`` event (and periodic
    ``heartbeat`` events) as it arrives.

    Extracted from ``_run_one_turn`` (B9/T-104) so it can be called a
    second time, unchanged, against ``get_chat_llm_fallback()``'s client
    when the first attempt fails before yielding anything (see
    ``_run_one_turn``'s own fallback-retry logic) -- the disconnect/
    heartbeat/send-failure handling below must behave identically on
    both attempts, which duplicating this loop inline twice could not
    guarantee would stay true as the loop evolves.

    Raises:
        ChatLLMError: the LLM call itself failed, or produced no
            tokens (see ``astream_chat_from_messages``'s own docstring)
            -- the caller decides whether a fallback-provider retry is
            possible (only when the returned/collected list is empty).
        _StreamAlreadyHandled: a client disconnect or a send failure on
            an already-broken connection occurred; any partial reply is
            already persisted and the caller must not retry or send
            anything further -- it should simply return.
    """
    collected: list[str] = []
    idle_ticks = 0
    pending_next: Optional["asyncio.Task[str]"] = None

    try:
        token_iter = _reply_token_source(
            cached_reply, immediate_text, messages, llm
        ).__aiter__()

        while True:
            # IMPORTANT: do not wrap token_iter.__anext__() directly in
            # asyncio.wait_for(). wait_for() CANCELS its awaitable the
            # instant it times out, and cancelling an async generator's
            # in-flight __anext__() call destroys the generator's
            # paused state -- the very next __anext__() call on the
            # same iterator then raises StopAsyncIteration immediately,
            # silently truncating the reply to nothing the moment a
            # single token takes longer than _TOKEN_POLL_INTERVAL_SECONDS
            # to arrive (an entirely realistic wait for a real
            # provider's first token). asyncio.wait() below never
            # cancels on timeout -- it only reports whether the SAME
            # long-lived Task has finished yet -- so a slow-to-arrive
            # token is polled for repeatedly without ever losing
            # progress. The task is created once per token and re-used
            # across every timeout iteration until it actually
            # resolves; it is only ever cancelled in this loop's exit
            # paths below (disconnect, send failure), where abandoning
            # the in-flight generation is the correct, intended outcome.
            if pending_next is None:
                pending_next = asyncio.ensure_future(token_iter.__anext__())

            # BUGFIX: the disconnect probe below used to be
            # ``_client_still_connected(websocket)``, which cancelled a
            # fresh ``websocket.receive()`` call every idle tick -- see
            # ``_InboundReader``'s class docstring for the full
            # explanation of why that corrupted the connection (the
            # actual root cause of the "AIRP Assistant failed to
            # generate a response" report). ``reader.task`` is the
            # SAME never-cancelled-mid-flight receive task
            # ``_turn_loop`` itself waits on between turns; waiting on
            # it here too (never cancelling it) is what makes it safe
            # to share.
            done, _pending = await asyncio.wait(
                {pending_next, reader.task},
                timeout=_TOKEN_POLL_INTERVAL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if reader.task in done and pending_next not in done:
                try:
                    message = reader.advance()
                except WebSocketDisconnect:
                    message = {"type": "websocket.disconnect"}
                except Exception:
                    message = {"type": "websocket.disconnect"}

                if message.get("type") == "websocket.disconnect":
                    pending_next.cancel()
                    await _persist_interrupted_reply(session_id, collected)
                    raise _StreamAlreadyHandled()
                # A benign, unexpected message mid-reply -- this
                # endpoint has no mid-turn client protocol, so it is
                # ignored (reader.task has already been advanced to
                # listen for the next one). Fall through to the
                # idle/heartbeat bookkeeping below since the token
                # itself has not necessarily arrived yet.

            if pending_next not in done:
                # Still waiting on the same in-flight token call --
                # send a heartbeat if it has been quiet long enough,
                # then loop back and keep waiting on it (not a new one).
                idle_ticks += 1
                if idle_ticks >= _HEARTBEAT_AFTER_TICKS:
                    idle_ticks = 0
                    try:
                        await websocket.send_json(
                            _cast_stream_event(session_id, event_type="heartbeat")
                        )
                    except Exception:
                        pending_next.cancel()
                        await _persist_interrupted_reply(session_id, collected)
                        raise _StreamAlreadyHandled()
                continue

            try:
                token = pending_next.result()
            except StopAsyncIteration:
                break
            finally:
                pending_next = None

            idle_ticks = 0
            collected.append(token)

            try:
                await websocket.send_json(
                    _cast_stream_event(session_id, event_type="token", token=token)
                )
            except Exception:
                await _persist_interrupted_reply(session_id, collected)
                raise _StreamAlreadyHandled()
    except ChatLLMError as exc:
        # Attach whatever was collected before this failed -- see
        # ChatLLMError.collected_tokens's own docstring for why the
        # caller needs this to decide whether a fallback-provider retry
        # is safe.
        exc.collected_tokens = collected
        raise
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()

    return collected


def _extract_started_analysis_job_id(messages: list[BaseMessage]) -> Optional[str]:
    """
    Scan a tool-calling round's updated message list for a successful
    ``request_new_analysis`` result (FEATURE 1).

    ``backend.tools.portfolio_tools.request_new_analysis`` returns
    ``{"status": "started", "job_id": ..., ...}`` as a JSON-encoded
    ``ToolMessage`` (see ``run_tool_calling_round``'s own docstring --
    every tool result, success or error, becomes one ``ToolMessage``
    appended to the message list). This is a generic scan over
    ``ToolMessage`` content shape rather than one keyed to a specific
    tool_call_id/name, since that shape (``status`` + ``job_id``
    together) is unique to this one tool's success response -- no other
    tool in this codebase returns both keys.

    Args:
        messages: The message list AFTER ``run_tool_calling_round`` --
            unchanged (== the original list, no ``ToolMessage`` added)
            when no tool was called, in which case this returns None.

    Returns:
        The job_id string, or None if no successful
        request_new_analysis call is present. Never raises -- a
        malformed/non-JSON ToolMessage content is simply skipped.
    """
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        content = message.content
        if not isinstance(content, str):
            continue
        try:
            parsed: Any = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            isinstance(parsed, dict)
            and parsed.get("status") == "started"
            and isinstance(parsed.get("job_id"), str)
        ):
            return str(parsed["job_id"])
    return None


async def _run_one_turn(
    websocket: WebSocket,
    session_id: uuid.UUID,
    user: User,
    info: ChatSessionStreamInfo,
    user_message: str,
    reader: "_InboundReader",
) -> None:
    """
    Stream exactly one AIRP Assistant reply for ``user_message``.

    Loads history/context, persists the user's message, streams the
    reply token by token, then persists the assistant's message. Never
    raises -- every failure mode (bad context load, LLM failure,
    mid-stream disconnect) is handled inline so ``_turn_loop`` can
    always safely continue to the next iteration (or return, for a
    detected disconnect).

    B9 additions:
      * Reply cache (backend.services.chat_cache) -- an identical
        question (normalised) asked again within the cache TTL, for the
        same user and the same session scope (the analysis_id for a
        memo-scoped session, a fixed placeholder for portfolio-wide),
        is served from Redis instead of re-invoking the LLM/tools.
      * Tool-calling (backend.services.chat_llm.run_tool_calling_round)
        -- see ``_build_chat_tools``'s docstring for the root cause this
        closes. Deliberately run INSIDE this function's own DB session
        block (below), even though the rest of that block is unrelated
        to tools: backend.tools.portfolio_tools' two DB-backed tools are
        bound to THIS turn's session via a closure and must be executed
        before it closes -- see backend/routers/chat_stream.py's module
        docstring for why the session is otherwise closed before
        streaming begins. A tool-round failure is captured as a
        ChatLLMError here rather than left to propagate, so it is
        reported to the client the same way a streaming failure already
        is, further down.
    """
    session_scope = (
        str(info.analysis_id) if info.analysis_id is not None else PORTFOLIO_SCOPE
    )
    cache_key = build_cache_key(user.id, session_scope, user_message)
    cached_reply = get_cached_reply(cache_key)

    messages: list[BaseMessage] = []
    immediate_text: Optional[str] = None
    tool_round_error: Optional[ChatLLMError] = None
    analysis_job_id: Optional[str] = None

    async with AsyncSessionLocal() as db_session:
        history_page = await get_chat_session_messages(
            db_session,
            user_id=user.id,
            session_id=session_id,
            limit=MAX_MESSAGES_PAGE_SIZE,
        )
        history: list[dict[str, str]] = (
            [{"role": m.role, "content": m.content} for m in history_page.items]
            if history_page is not None
            else []
        )

        context: Optional[str] = None
        if info.session_type == "memo_scoped" and info.analysis_id is not None:
            try:
                memo_context = await build_memo_context(
                    db_session, info.analysis_id, user.id
                )
                context = (
                    memo_context.full_context if memo_context is not None else None
                )
            except AnalysisNotReadyError:
                # Should not happen -- T-103's create_chat_session only
                # allows a memo_scoped session against an
                # already-completed analysis -- but degrade rather than
                # crash the turn if the analysis's state ever changes
                # underneath an existing session.
                logger.warning(
                    "chat_stream: analysis_id=%s no longer ready for "
                    "session_id=%s -- continuing without grounded context",
                    info.analysis_id,
                    session_id,
                )
                context = None

        # Personalization (T-106). Recognise (deterministically, no LLM
        # call -- see preference_extractor.py's own docstring) any
        # risk appetite / preferred sectors the user just stated, and
        # persist anything newly learned into a still-unset field only
        # -- see preference_service.py's own docstring for why an
        # already-known preference is never silently overwritten by a
        # later, more casual mention. Also picks up chat_response_style
        # from the same row, replacing the constant this router used
        # through T-104/T-105 -- see the module docstring's "Why
        # response_style is now read from user_preferences..." section.
        extraction = extract_preferences(user_message)
        preferences = await apply_extracted_preferences(db_session, user.id, extraction)

        saved_user_message = await append_chat_message(
            db_session, session_id=session_id, role="user", content=user_message
        )

        if cached_reply is None:
            tools = _build_chat_tools(db_session, user, info.session_type)
            messages = build_chat_messages(
                history,
                user_message,
                response_style=preferences.chat_response_style,
                context=context,
                risk_appetite=preferences.risk_appetite,
                preferred_sectors=preferences.preferred_sectors,
                tools_available=bool(tools),
                # FEATURE 1: request_new_analysis is bound only for
                # portfolio-wide sessions (see _build_chat_tools) -- this
                # tells the model it can start a new analysis without a
                # separate signal, since session_type itself already
                # determines whether that tool is among `tools`.
                can_request_analysis=info.session_type == "portfolio_wide",
            )
            if tools:
                try:
                    messages, immediate_text = await run_tool_calling_round(
                        get_chat_llm(), tools, messages
                    )
                    analysis_job_id = _extract_started_analysis_job_id(messages)
                except Exception as exc:
                    fallback_llm = get_chat_llm_fallback()
                    if fallback_llm is None:
                        logger.exception(
                            "chat_stream: tool-calling round failed for session_id=%s",
                            session_id,
                        )
                        tool_round_error = ChatLLMError(
                            "AIRP Assistant failed to generate a response.", cause=exc
                        )
                    else:
                        # Root cause behind most real-world "failed to
                        # generate a response" reports: the primary
                        # provider's rate/quota limit, not a genuine bug
                        # -- see get_chat_llm_fallback's own docstring.
                        # One more attempt on the second configured
                        # provider before the turn actually fails.
                        logger.warning(
                            "chat_stream: tool-calling round failed for "
                            "session_id=%s, retrying once on the fallback "
                            "LLM provider: %s",
                            session_id,
                            exc,
                        )
                        try:
                            messages, immediate_text = await run_tool_calling_round(
                                fallback_llm, tools, messages
                            )
                            analysis_job_id = _extract_started_analysis_job_id(messages)
                        except Exception as fallback_exc:
                            logger.exception(
                                "chat_stream: tool-calling round failed on the "
                                "fallback provider too for session_id=%s",
                                session_id,
                            )
                            tool_round_error = ChatLLMError(
                                "AIRP Assistant failed to generate a response.",
                                cause=fallback_exc,
                            )

    if tool_round_error is not None:
        try:
            await websocket.send_json(
                _cast_stream_event(
                    session_id,
                    event_type="error",
                    error=str(tool_round_error),
                    is_final=True,
                )
            )
        except Exception:  # nosec B110 -- best-effort notify on a failing connection
            pass
        return

    try:
        await websocket.send_json(
            _cast_stream_event(
                session_id,
                event_type="start",
                message_id=saved_user_message.id,
                analysis_job_id=analysis_job_id,
            )
        )
    except Exception:
        return

    try:
        collected = await _poll_reply_tokens(
            websocket,
            reader,
            session_id,
            cached_reply,
            immediate_text,
            messages,
            get_chat_llm(),
        )
    except _StreamAlreadyHandled:
        return
    except ChatLLMError as exc:
        # A fallback-provider retry only makes sense when NOTHING was
        # streamed yet on the failed attempt -- astream_chat_from_messages
        # raises the same ChatLLMError whether zero tokens ever came out
        # or a failure happened mid-stream (see its own docstring), so
        # exc.collected_tokens (attached by _poll_reply_tokens before
        # re-raising) is what actually distinguishes the two cases, not
        # the exception type.
        collected = exc.collected_tokens
        fallback_llm = get_chat_llm_fallback() if not collected else None
        if fallback_llm is None:
            try:
                await websocket.send_json(
                    _cast_stream_event(
                        session_id, event_type="error", error=str(exc), is_final=True
                    )
                )
            except (
                Exception
            ):  # nosec B110 -- best-effort notify on a failing connection
                pass
            if collected:
                await _persist_interrupted_reply(session_id, collected)
            return
        # Root cause behind most real-world "failed to generate a
        # response" reports: the primary provider's rate/quota limit,
        # not a genuine bug -- see get_chat_llm_fallback's own
        # docstring. One more attempt on the second configured provider
        # before the turn actually fails.
        logger.warning(
            "chat_stream: streaming reply failed for session_id=%s before "
            "any token was produced, retrying once on the fallback LLM "
            "provider: %s",
            session_id,
            exc,
        )
        try:
            collected = await _poll_reply_tokens(
                websocket,
                reader,
                session_id,
                cached_reply,
                immediate_text,
                messages,
                fallback_llm,
            )
        except _StreamAlreadyHandled:
            return
        except ChatLLMError as fallback_exc:
            try:
                await websocket.send_json(
                    _cast_stream_event(
                        session_id,
                        event_type="error",
                        error=str(fallback_exc),
                        is_final=True,
                    )
                )
            except (
                Exception
            ):  # nosec B110 -- best-effort notify on a failing connection
                pass
            if fallback_exc.collected_tokens:
                await _persist_interrupted_reply(
                    session_id, fallback_exc.collected_tokens
                )
            return

    full_text = "".join(collected)

    if cached_reply is None and full_text:
        # Only cache a FRESHLY generated, complete reply -- never a
        # cache hit re-cached against itself (a no-op, but wasted work),
        # and never an empty string (would poison the cache with a
        # blank answer for the next identical question).
        set_cached_reply(cache_key, full_text)

    async with AsyncSessionLocal() as db_session:
        saved = await append_chat_message(
            db_session, session_id=session_id, role="assistant", content=full_text
        )

    try:
        await websocket.send_json(
            _cast_stream_event(
                session_id,
                event_type="done",
                message_id=saved.id,
                is_final=True,
            )
        )
    except Exception:
        # Client is already gone by the time the reply finished -- the
        # message is safely persisted above regardless, so there is
        # nothing further to do.
        return


async def _persist_interrupted_reply(
    session_id: uuid.UUID, collected: list[str]
) -> None:
    """
    Save whatever partial reply had been generated before a mid-stream
    disconnect was detected -- see "Why reconnecting... just works" in
    the module docstring. A no-op when nothing had been generated yet.
    """
    if not collected:
        return
    try:
        async with AsyncSessionLocal() as db_session:
            await append_chat_message(
                db_session,
                session_id=session_id,
                role="assistant",
                content=_INTERRUPTED_PREFIX + "".join(collected),
            )
    except Exception:
        logger.exception(
            "chat_stream: failed to persist interrupted reply for session_id=%s",
            session_id,
        )
