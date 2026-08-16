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
  ``_forward_live_events`` (``asyncio.wait_for(..., timeout=...)``
  around the next item, a heartbeat after N consecutive timeouts, a
  zero-timeout ``receive()`` to detect a dead TCP connection between
  real events) -- applied here to ``astream_chat``'s own async
  iterator instead of a broadcaster queue, since (per the point above)
  there is no queue in this design, only the LLM's own token stream to
  poll the same way.
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

Known scope boundary: portfolio-wide tool-calling is not wired into
this loop
------------------------------------------------------------------------
T-101 already built the three portfolio-wide LangChain tools
(``backend.tools.portfolio_tools.build_portfolio_tools``), but this
router does not bind them to the streaming LLM call. A
``session_type='portfolio_wide'`` connection still works end-to-end --
the guardrail persona and streaming mechanics are fully functional --
it simply cannot yet answer questions that require looking up the
user's other analyses or searching uploaded documents. Wiring T-101's
tools into a streaming tool-calling loop (interleaving tool-call
events with token events) is materially more scope than "reuse the
ws_broadcaster pattern for token-by-token streaming" asks for, and is
called out explicitly here rather than silently left unfinished.

Design decisions
------------------------------------------------------------------------
* No ``from __future__ import annotations`` -- matches every other
  router in this codebase.
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
"""

import asyncio
import logging
from typing import Any, Optional, TypedDict
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import AsyncSessionLocal
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.services.analysis import AnalysisNotReadyError
from backend.services.auth import InvalidTokenError, decode_access_token
from backend.services.chat_llm import ChatLLMError, astream_chat
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
      'token'     -- one incremental chunk of the assistant's reply.
      'heartbeat' -- no new token in a while; keeps the connection
                      alive during a slow first-token wait. Carries no
                      new content (token == "").
      'done'      -- the reply finished successfully. ``message_id``
                      is the persisted ChatMessage's id.
      'error'     -- the turn failed (bad client input, or the LLM
                      call itself failed). The connection stays open;
                      the client may send another message.
    """

    session_id: str
    event_type: str
    token: str
    message_id: Optional[str]
    is_final: bool
    error: Optional[str]


def _cast_stream_event(
    session_id: uuid.UUID,
    event_type: str,
    token: str = "",
    message_id: Optional[uuid.UUID] = None,
    is_final: bool = False,
    error: Optional[str] = None,
) -> ChatStreamEvent:
    return ChatStreamEvent(
        session_id=str(session_id),
        event_type=event_type,
        token=token,
        message_id=str(message_id) if message_id is not None else None,
        is_final=is_final,
        error=error,
    )


# ---------------------------------------------------------------------------
# Auth -- query-param token (duplicated from backend.routers.websocket;
# see module docstring for why)
# ---------------------------------------------------------------------------


async def _authenticate(
    token: str, session: AsyncSession, settings: Settings
) -> Optional[User]:
    """Resolve a query-param bearer token to a User row, or None."""
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

    await _turn_loop(websocket, session_id=session_id, user=user, info=stream_info)


async def _turn_loop(
    websocket: WebSocket,
    session_id: uuid.UUID,
    user: User,
    info: ChatSessionStreamInfo,
) -> None:
    """
    Receive client messages and stream one AIRP Assistant reply per
    message, until the client disconnects.

    Extracted from ``stream_chat`` so the connect-time auth/ownership
    checks above stay separate from the (much longer) per-turn
    streaming logic.
    """
    while True:
        try:
            payload = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except Exception:
            # Malformed JSON, or some other receive-path error that is
            # not a clean disconnect -- tell the client and keep
            # listening rather than tearing the connection down.
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

        assert user_message is not None  # narrowed by the check above
        await _run_one_turn(
            websocket,
            session_id=session_id,
            user=user,
            info=info,
            user_message=user_message,
        )


async def _run_one_turn(
    websocket: WebSocket,
    session_id: uuid.UUID,
    user: User,
    info: ChatSessionStreamInfo,
    user_message: str,
) -> None:
    """
    Stream exactly one AIRP Assistant reply for ``user_message``.

    Loads history/context, persists the user's message, streams the
    reply token by token, then persists the assistant's message. Never
    raises -- every failure mode (bad context load, LLM failure,
    mid-stream disconnect) is handled inline so ``_turn_loop`` can
    always safely continue to the next iteration (or return, for a
    detected disconnect).
    """
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

        await append_chat_message(
            db_session, session_id=session_id, role="user", content=user_message
        )

    try:
        await websocket.send_json(_cast_stream_event(session_id, event_type="start"))
    except Exception:
        return

    collected: list[str] = []
    idle_ticks = 0
    pending_next: Optional["asyncio.Task[str]"] = None

    try:
        token_iter = astream_chat(
            history,
            user_message,
            response_style=preferences.chat_response_style,
            context=context,
            risk_appetite=preferences.risk_appetite,
            preferred_sectors=preferences.preferred_sectors,
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

            done, _pending = await asyncio.wait(
                {pending_next}, timeout=_TOKEN_POLL_INTERVAL_SECONDS
            )

            if pending_next not in done:
                # Still waiting on the same in-flight call -- probe for
                # a client-initiated disconnect and/or send a heartbeat,
                # then loop back and keep waiting on it (not a new one).
                if not await _client_still_connected(websocket):
                    pending_next.cancel()
                    await _persist_interrupted_reply(session_id, collected)
                    return

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
                        return
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
                return

    except ChatLLMError as exc:
        try:
            await websocket.send_json(
                _cast_stream_event(
                    session_id, event_type="error", error=str(exc), is_final=True
                )
            )
        except Exception:
            pass
        if collected:
            await _persist_interrupted_reply(session_id, collected)
        return
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()

    full_text = "".join(collected)
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


async def _client_still_connected(websocket: WebSocket) -> bool:
    """
    Best-effort liveness probe -- identical technique and rationale to
    ``backend.routers.websocket._client_still_connected`` (T-049): a
    zero-timeout ``receive()`` surfaces an already-buffered
    disconnect/EOF without blocking a live connection that has nothing
    to say (this endpoint defines no other client -> server protocol
    beyond the ``{"message": ...}`` turns already read in
    ``_turn_loop``, so any other payload received here is simply
    ignored, same as T-049's own equivalent).
    """
    try:
        await asyncio.wait_for(websocket.receive(), timeout=0.01)
    except asyncio.TimeoutError:
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        return False
    return True
