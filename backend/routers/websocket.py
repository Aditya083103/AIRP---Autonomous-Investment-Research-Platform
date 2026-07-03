# backend/routers/websocket.py
"""
AIRP -- WebSocket Live Progress Streaming Router (T-049)

WS /api/v1/analysis/{job_id}/stream

Acceptance criteria (from task spec):
  * WebSocket sends event per agent completion
  * Frontend receives and displays in order
  * Connection closes cleanly

What this endpoint does
------------------------
Lets a client follow an analysis job in real time instead of polling
T-048's GET /api/v1/analysis/{job_id}/status. On connect:

  1. Authenticates the caller via a ``token`` query parameter (a bearer
     JWT -- see "Why query-param auth" below), the same token issued by
     POST /auth/login.
  2. Confirms the job_id exists and belongs to the authenticated user
     via the exact same backend.services.analysis.get_analysis_status
     T-048 already uses -- closes with code 4404 (not a generic 1008)
     immediately if not, so a client can tell "this job is not mine or
     does not exist" apart from any other rejection reason.
  3. Sends one event immediately reflecting the job's CURRENT status --
     covers the common race where the pipeline runs to completion
     before the client's WebSocket finishes connecting (a fast
     analysis can complete in under 90 seconds; a client that was
     slightly slow to open the socket must not hang forever waiting
     for node-completion events that already happened).
  4. If that initial snapshot is already terminal (completed/failed),
     closes immediately afterward -- there is nothing further to
     stream.
  5. Otherwise subscribes to backend.services.ws_broadcaster and
     forwards every subsequent AgentStreamEvent published for this
     job_id, in the order backend.graph.nodes._run_broadcast publishes
     them (i.e. LangGraph's actual execution order), until the event
     marked ``is_final=True`` arrives, then closes cleanly (code 1000).

Why query-param auth instead of the Authorization header
-------------------------------------------------------------
Browsers' native WebSocket API cannot set custom request headers on
the opening handshake -- only the URL and protocol list are
controllable from JavaScript. backend.dependencies.auth.get_current_user
(T-046) is built around fastapi.security.OAuth2PasswordBearer reading
an Authorization header, which works for every existing HTTP route but
is unreachable from a browser's WebSocket constructor. A ``token``
query parameter is the standard, documented workaround for this exact
limitation (see Starlette/FastAPI's own WebSocket auth examples) --
this route therefore does its own lightweight verification via
backend.services.auth.decode_access_token directly, rather than
depending on get_current_user (which requires the OAuth2PasswordBearer
header dependency get_current_user itself depends on). ``settings`` is
still injected the normal way via ``Depends(get_settings_dependency)``
on the route function -- per-route ``Depends()`` parameters work
identically for WebSocket routes and HTTP routes in FastAPI (the only
documented limitation is that *global* ``dependencies=[...]`` declared
on the ``FastAPI()``/``APIRouter()`` constructor do not propagate to
WebSocket routes, which is irrelevant here since this router declares
no such global dependency). The database session is handled
differently -- see ``stream_analysis_progress``'s own docstring for
why it is opened as a narrow, manually-scoped ``async with`` block
instead of a ``Depends()`` parameter. The looked-up User row's id is
used for the same ownership check every other authenticated route
performs.

Why a custom close code (4404) instead of denying the handshake
---------------------------------------------------------------------
Starlette's WebSocket route handlers can reject a connection before
``accept()`` (a "denial response"), but the browser-side WebSocket API
exposes almost no detail about *why* a handshake was denied -- only a
generic error. Accepting the connection first and then closing with an
application-specific code (4404, in the 4000-4999 range WebSocket's
own spec reserves for application use) lets a client distinguish "job
not found / not yours" from "bad or missing token" (4401) and from a
normal, successful stream completion (1000) -- useful for a future
Phase 6 frontend to show the right error state.

Public API
----------
    from backend.routers.websocket import router
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import AsyncSessionLocal
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.services.analysis import AnalysisStatusResult, get_analysis_status
from backend.services.auth import InvalidTokenError, decode_access_token
from backend.services.ws_broadcaster import (
    TERMINAL_STATUSES,
    AgentStreamEvent,
    cast_event,
    subscribe,
    unsubscribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# Close codes -- application-specific range (4000-4999 per RFC 6455)
# ---------------------------------------------------------------------------

#: No token query param, or decode_access_token rejected it (expired,
#: malformed, wrong signature, or the user it names no longer exists /
#: is deactivated) -- mirrors the 401 every HTTP route returns for the
#: identical failure via get_current_user.
_CLOSE_UNAUTHORIZED = 4401

#: job_id does not exist, or exists but belongs to a different user.
#: Deliberately one code for both cases -- same enumeration-prevention
#: rationale as backend.services.analysis.get_analysis_status's
#: identical None-for-both-cases contract (see that function's
#: docstring): telling a non-owner "this exists, just not yours" would
#: itself leak which job_id UUIDs are real.
_CLOSE_NOT_FOUND = 4404

#: How long the forwarding loop waits on the broadcaster queue before
#: polling the WebSocket for a client-initiated disconnect. Short
#: enough that a disconnect is noticed promptly (so a dead connection's
#: subscriber queue does not linger for the full ~90s pipeline runtime);
#: long enough that this is not a busy-poll -- the queue.get() call
#: itself returns immediately the moment a real event is published, so
#: this timeout only matters during the (much more common) gaps
#: between node completions.
_QUEUE_POLL_INTERVAL_SECONDS = 2.0

#: How many consecutive poll-interval timeouts (i.e. how many seconds,
#: at _QUEUE_POLL_INTERVAL_SECONDS each) may pass with no real node
#: event before a lightweight heartbeat is pushed to the client. At the
#: default 2s poll interval this is 10s -- comfortably under the
#: ~30-60s idle-connection timeout many home routers, corporate
#: proxies, and some browsers enforce on a WebSocket carrying no
#: traffic in either direction. Without this, a slow LLM call (a Groq
#: free-tier rate limit forcing an agent to wait/retry for 30-40+
#: seconds is the observed real-world trigger) can leave the socket
#: completely silent long enough for an intermediary to drop the
#: connection with an abnormal closure (code 1006) even though the
#: backend pipeline is still healthy and will complete normally in the
#: background.
_HEARTBEAT_AFTER_TICKS = 5


# ---------------------------------------------------------------------------
# Auth -- query-param token (browsers cannot set WS handshake headers)
# ---------------------------------------------------------------------------


async def _authenticate(
    token: str, session: AsyncSession, settings: Settings
) -> User | None:
    """
    Resolve a query-param bearer token to a User row.

    Mirrors backend.dependencies.auth.get_current_user's verification
    logic exactly (decode -> parse sub as UUID -> load User -> check
    is_active) but returns None on any failure instead of raising
    HTTPException, since a WebSocket route closes the connection with
    an explicit code rather than relying on FastAPI's HTTP exception
    handling (which does not apply once the handshake is accepted).

    Args:
        token:    Raw bearer token string from the ``token`` query param.
        session:  Active AsyncSession for this connection.
        settings: Resolved Settings (via Depends(get_settings_dependency)
                  on the caller), so tests can override it exactly like
                  every HTTP route already does -- this function never
                  calls backend.config.get_settings() itself.

    Returns:
        The authenticated User, or None for any invalid/expired token,
        a token naming a UUID with no matching row, or a deactivated
        account.
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
    return user


# ---------------------------------------------------------------------------
# Event construction -- initial snapshot (before any new node completes)
# ---------------------------------------------------------------------------


def _snapshot_to_event(
    job_id: uuid.UUID, snapshot: AnalysisStatusResult
) -> AgentStreamEvent:
    """
    Build the connect-time AgentStreamEvent from a GET /status snapshot.

    Reuses backend.services.analysis.AnalysisStatusResult (the exact
    same computation T-048 performs) rather than introducing a second
    way to describe "where is this job right now" -- the initial event
    a client receives immediately on connect and the response a client
    would get from a plain GET /status at that same instant are
    therefore always identical in substance, just delivered over a
    different transport.

    The ``agent`` field uses ``completed_nodes[-1]`` (the most
    recently finished node) when available, falling back to a
    'pipeline' placeholder for a job that has not started yet
    (completed_nodes is empty while status='pending') -- there is no
    real "agent" to attribute the snapshot to until the planner's first
    checkpoint exists.

    Args:
        job_id:   UUID of the analysis job.
        snapshot: Result of get_analysis_status for this job_id.

    Returns:
        An AgentStreamEvent summarising the job's current state.
    """
    agent = snapshot.completed_nodes[-1] if snapshot.completed_nodes else "pipeline"
    is_final = snapshot.status in TERMINAL_STATUSES
    output_preview = snapshot.error_message or snapshot.current_phase

    return cast_event(
        job_id=str(job_id),
        agent=agent,
        status=snapshot.status,
        output_preview=output_preview,
        progress_percent=snapshot.progress_percent,
        is_final=is_final,
    )


# ---------------------------------------------------------------------------
# WS /api/v1/analysis/{job_id}/stream
# ---------------------------------------------------------------------------


@router.websocket("/{job_id}/stream")
async def stream_analysis_progress(
    websocket: WebSocket,
    job_id: uuid.UUID,
    settings: Settings = Depends(get_settings_dependency),
) -> None:
    """
    Stream live agent-completion events for one analysis job.

    See the module docstring for the full connect/auth/replay/forward/
    close sequence. This handler never lets an exception escape
    unhandled -- every failure path closes the socket with an explicit
    code rather than letting Starlette's default error handling tear
    the connection down silently.

    Unlike ``settings``, the database session is deliberately NOT
    injected via ``Depends(get_async_session)`` for the whole
    connection: a FastAPI dependency resolved on a WebSocket route is
    held open for the entire lifetime of the connection, not
    re-resolved per message -- which would mean checking out a pooled
    PostgreSQL connection (Neon's free tier has a modest connection
    cap; see backend/db/session.py) for the full ~90 second streaming
    duration even though the DB is only actually touched once, up
    front, for auth and the initial snapshot. Instead, a session is
    opened via ``AsyncSessionLocal()`` as a narrow ``async with`` block
    scoped to exactly that initial phase, then closed before entering
    ``_forward_live_events`` -- the long-lived streaming loop -- which
    needs no further database access at all.

    Args:
        websocket: The WebSocket connection, injected by FastAPI/Starlette.
        job_id:    Path parameter, parsed and validated as a UUID by
                   FastAPI before this function is even called -- an
                   unparsable job_id closes the handshake automatically.
        settings:  Injected via Depends(get_settings_dependency) -- the
                   same dependency every HTTP route uses, so tests
                   override it identically via
                   app.dependency_overrides[get_settings_dependency].
                   Safe to hold for the connection's full lifetime --
                   unlike a DB session, it is an immutable, in-memory
                   value with no pooled resource behind it.
    """
    token = websocket.query_params.get("token", "")

    await websocket.accept()

    async with AsyncSessionLocal() as session:
        user = await _authenticate(token, session, settings) if token else None
        if user is None:
            await websocket.close(code=_CLOSE_UNAUTHORIZED)
            return

        snapshot = await get_analysis_status(
            session,
            job_id=job_id,
            user_id=user.id,
        )

    if snapshot is None:
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    try:
        await websocket.send_json(_snapshot_to_event(job_id, snapshot))
    except Exception:
        # Client disconnected before the very first send could land --
        # nothing left to clean up (no subscriber was ever registered).
        return

    if snapshot.status in TERMINAL_STATUSES:
        await websocket.close(code=1000)
        return

    await _forward_live_events(websocket, job_id)


async def _forward_live_events(websocket: WebSocket, job_id: uuid.UUID) -> None:
    """
    Subscribe to the broadcaster and forward events until the final one.

    Extracted from ``stream_analysis_progress`` so the subscribe/
    unsubscribe pairing has a single, narrow ``try``/``finally`` --
    once subscribed, this function guarantees ``unsubscribe`` runs on
    every exit path (normal completion, client disconnect, or any other
    exception), so a job_id can never accumulate a leaked subscriber
    for the lifetime of the process.

    Also pushes a lightweight heartbeat event (see
    ``_HEARTBEAT_AFTER_TICKS``) whenever real node-completion events
    stop arriving for too long -- e.g. an agent stuck retrying against
    a rate-limited LLM provider -- so the socket is never silent long
    enough for a router/proxy/browser idle-connection timeout to close
    it out from under a still-healthy pipeline.

    Args:
        websocket: The accepted, already-authenticated connection.
        job_id:    UUID of the analysis job to stream.
    """
    queue = await subscribe(str(job_id))
    idle_ticks = 0
    last_progress_percent = 0
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=_QUEUE_POLL_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                # No node completed within the poll interval -- probe
                # for a client-initiated disconnect with a zero-timeout
                # receive rather than blocking indefinitely on queue.get()
                # while a dead connection's subscriber sits registered.
                if not await _client_still_connected(websocket):
                    return

                idle_ticks += 1
                if idle_ticks >= _HEARTBEAT_AFTER_TICKS:
                    idle_ticks = 0
                    heartbeat = cast_event(
                        job_id=str(job_id),
                        agent="pipeline",
                        status="running",
                        output_preview="Still working -- no update yet.",
                        progress_percent=last_progress_percent,
                        is_final=False,
                    )
                    try:
                        await websocket.send_json(heartbeat)
                    except Exception:
                        # Send failed -- the connection is gone. Nothing
                        # further to forward.
                        return
                continue

            idle_ticks = 0
            last_progress_percent = event["progress_percent"]

            try:
                await websocket.send_json(event)
            except Exception:
                # Send failed -- the connection is gone. Nothing further
                # to forward.
                return

            if event["is_final"]:
                await websocket.close(code=1000)
                return
    finally:
        await unsubscribe(str(job_id), queue)


async def _client_still_connected(websocket: WebSocket) -> bool:
    """
    Best-effort check for whether ``websocket`` is still connected.

    A WebSocket's TCP connection can drop without the server ever
    receiving a close frame -- Starlette/FastAPI does not surface this
    on its own (see the module docstring's "Why a custom close code"
    section for the analogous header-access limitation; this is the
    same "browsers/networks don't tell the server everything" class of
    constraint). The standard workaround -- used here -- is a
    zero-timeout ``receive`` call: if the connection is actually dead,
    Starlette raises ``WebSocketDisconnect`` as soon as it processes
    the already-buffered close/EOF event, which a live connection with
    nothing to say will not do within the (effectively instant) timeout.

    Args:
        websocket: The connection to probe.

    Returns:
        True if the connection still appears live, False if a
        disconnect was detected.
    """
    try:
        await asyncio.wait_for(websocket.receive(), timeout=0.01)
    except asyncio.TimeoutError:
        return True
    except WebSocketDisconnect:
        return False
    except Exception:
        # Any other receive-path error is treated as "connection is no
        # longer usable" -- safer to stop forwarding than to keep
        # writing to a socket in an unknown state.
        return False
    # The client sent something we did not expect on a server-push-only
    # stream (this endpoint defines no client->server protocol). Still
    # connected; the message itself is simply ignored.
    return True
