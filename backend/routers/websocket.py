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


def _snapshot_to_events(
    job_id: uuid.UUID, snapshot: AnalysisStatusResult
) -> list[AgentStreamEvent]:
    """
    Build the connect-time AgentStreamEvent(s) from a GET /status snapshot.

    BUGFIX (found during live end-to-end verification): this used to
    return a SINGLE event naming only ``completed_nodes[-1]`` (the most
    recently finished node). A client connecting for the first time
    after the job already progressed past node 1 -- the common case for
    anyone who reloads the page, whose WebSocket drops and never
    reconnects, or who opens a link to a job that finished minutes ago --
    would then see only that one node as "complete" and every earlier
    node (e.g. all 4 parallel research agents, if the last-completed
    node is later in the pipeline) misrendered as "skipped"
    (frontend/src/lib/agentProgress.ts's deriveAgentCards has no way to
    know a node it never received an event for actually ran).

    Fix: emit one event per entry in ``snapshot.completed_nodes``, in
    pipeline order, exactly reconstructing what a client that had been
    connected from the start would have received. Every entry gets
    ``status="completed"`` and ``is_final=False`` EXCEPT the last, which
    carries the snapshot's real ``status`` (so a failed run still shows
    as failed, not completed) and ``is_final`` set from whether that
    status is terminal -- unchanged from this function's original
    single-event contract, just now preceded by the historical replay.

    SECOND BUGFIX, same investigation: ``snapshot.completed_nodes`` comes
    from ``backend.services.analysis.compute_progress``, which walks
    ``CANONICAL_NODE_SEQUENCE`` -- a deliberately COLLAPSED view of the
    graph that represents the 4 parallel research agents (fundamental
    analyst, technical analyst, news sentiment, macro economist) as the
    single ``research_join`` barrier node they all feed into, never by
    their own names (see that module's own CANONICAL_NODE_SEQUENCE
    docstring). Replaying events using those names verbatim therefore
    NEVER produces an event for any of those 4 agents individually --
    frontend/src/lib/agentProgress.ts's COMMITTEE_ROSTER expects an event
    per agent, so all 4 permanently rendered "skipped" even on a
    perfectly successful run, every single time a client connected after
    the fact rather than from the very start. Fixed by expanding
    ``research_join`` into 5 replayed events (the 4 agents, in the same
    order backend.graph.graph.build_graph's Send-API fan-out lists them,
    then research_join itself) whenever it appears in completed_nodes --
    research_join is a LangGraph join/barrier node, so its presence in
    completed_nodes already guarantees all 4 fed into it have finished.

    A job with no completed_nodes yet (status='pending') still gets
    exactly one event, naming a 'pipeline' placeholder agent, matching
    the pre-fix behaviour for that case exactly.

    Reuses backend.services.analysis.AnalysisStatusResult (the exact
    same computation T-048 performs) rather than introducing a second
    way to describe "where is this job right now" -- the events a
    client receives immediately on connect and the response a client
    would get from a plain GET /status at that same instant are
    therefore always consistent, just delivered over a different
    transport.

    Args:
        job_id:   UUID of the analysis job.
        snapshot: Result of get_analysis_status for this job_id.

    Returns:
        A non-empty list of AgentStreamEvent, in pipeline order, ending
        with one that summarises the job's current overall state.
    """
    if not snapshot.completed_nodes:
        return [
            cast_event(
                job_id=str(job_id),
                agent="pipeline",
                status=snapshot.status,
                output_preview=snapshot.error_message or snapshot.current_phase,
                progress_percent=snapshot.progress_percent,
                is_final=snapshot.status in TERMINAL_STATUSES,
            )
        ]

    # Lazy import -- backend.graph.nodes transitively pulls in every agent
    # module (LLM factory, langchain, ...); nothing else in this router
    # needs that weight paid at app-startup import time, so it is deferred
    # to first use here, matching backend.graph.nodes._run_broadcast's own
    # established lazy-import pattern for the identical reason.
    from backend.graph.nodes import (
        NODE_FUNDAMENTAL,
        NODE_MACRO,
        NODE_RESEARCH_JOIN,
        NODE_SENTIMENT,
        NODE_TECHNICAL,
    )

    replay_nodes: list[str] = []
    for node_name in snapshot.completed_nodes:
        if node_name == NODE_RESEARCH_JOIN:
            # research_join is a LangGraph join/barrier node -- it only
            # ever completes after all 4 parallel research agents have,
            # even though compute_progress's CANONICAL_NODE_SEQUENCE
            # names only the barrier itself, never the 4 agents feeding
            # into it (see this function's own docstring).
            replay_nodes.extend(
                [NODE_FUNDAMENTAL, NODE_TECHNICAL, NODE_SENTIMENT, NODE_MACRO]
            )
        replay_nodes.append(node_name)

    events: list[AgentStreamEvent] = [
        cast_event(
            job_id=str(job_id),
            agent=node_name,
            status="completed",
            output_preview=snapshot.current_phase,
            progress_percent=snapshot.progress_percent,
            is_final=False,
        )
        for node_name in replay_nodes[:-1]
    ]

    last_node = replay_nodes[-1]
    is_final = snapshot.status in TERMINAL_STATUSES
    events.append(
        cast_event(
            job_id=str(job_id),
            agent=last_node,
            status=snapshot.status,
            output_preview=snapshot.error_message or snapshot.current_phase,
            progress_percent=snapshot.progress_percent,
            is_final=is_final,
        )
    )
    return events


def _replayed_node_names(snapshot: AnalysisStatusResult) -> set[str]:
    """
    The set of node names ``_snapshot_to_events`` above already covers
    for ``snapshot``, including the ``research_join`` -> 4-agent
    expansion.

    Used only by ``stream_analysis_progress`` to filter the small burst
    of live events that can race in through the broadcaster queue
    between ``subscribe()`` and the replay actually being sent (see the
    BUGFIX note on that call site) -- without this, a node that
    completes in that narrow window would be shown twice: once via
    ``_snapshot_to_events``'s replay and again via the live forward
    loop picking up the exact same completion from the queue.

    Args:
        snapshot: The same AnalysisStatusResult passed to
            ``_snapshot_to_events``.

    Returns:
        Node names already represented in that function's replay --
        empty for a job with no completed_nodes yet.
    """
    if not snapshot.completed_nodes:
        return set()

    from backend.graph.nodes import (
        NODE_FUNDAMENTAL,
        NODE_MACRO,
        NODE_RESEARCH_JOIN,
        NODE_SENTIMENT,
        NODE_TECHNICAL,
    )

    covered: set[str] = set()
    for node_name in snapshot.completed_nodes:
        if node_name == NODE_RESEARCH_JOIN:
            covered.update(
                {NODE_FUNDAMENTAL, NODE_TECHNICAL, NODE_SENTIMENT, NODE_MACRO}
            )
        covered.add(node_name)
    return covered


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

    # BUGFIX (found during live end-to-end verification): subscribing to
    # the broadcaster used to happen only once _forward_live_events was
    # entered, AFTER the DB round-trip for auth/snapshot below and AFTER
    # every replay event had already been sent over the wire -- both real
    # I/O, not instantaneous. Any node that completed and published in
    # that window was lost forever: too late for the replay (built from
    # an already-fetched, now-stale snapshot) and too early for the live
    # subscription (not registered yet). Invisible when each node takes
    # several real seconds (the common case), but a fast-degrading run
    # (e.g. every LLM call failing instantly on a Groq rate limit, so
    # several nodes complete within milliseconds of each other) could
    # lose multiple consecutive nodes' events this way -- observed live
    # as the Risk Officer/Contrarian Investor/Valuation Agent seats
    # showing "Skipped -- did not run" even though the completed
    # Investment Memo clearly included all three agents' real output.
    # Fix: subscribe FIRST, before any DB work or replay I/O, so there is
    # no window at all in which a published event has nowhere to land.
    # This can now race the OTHER way instead -- a node finishing between
    # subscribe() and the snapshot fetch would appear in BOTH the replay
    # (once the snapshot catches up to it) and the live queue -- so
    # _drain_already_replayed below discards exactly that overlap before
    # entering the main forward loop.
    queue = await subscribe(str(job_id))

    async with AsyncSessionLocal() as session:
        user = await _authenticate(token, session, settings) if token else None
        if user is None:
            await unsubscribe(str(job_id), queue)
            await websocket.close(code=_CLOSE_UNAUTHORIZED)
            return

        snapshot = await get_analysis_status(
            session,
            job_id=job_id,
            user_id=user.id,
        )

    if snapshot is None:
        await unsubscribe(str(job_id), queue)
        await websocket.close(code=_CLOSE_NOT_FOUND)
        return

    try:
        for event in _snapshot_to_events(job_id, snapshot):
            await websocket.send_json(event)
    except Exception:
        # Client disconnected before the very first send could land.
        await unsubscribe(str(job_id), queue)
        return

    if snapshot.status in TERMINAL_STATUSES:
        await unsubscribe(str(job_id), queue)
        await websocket.close(code=1000)
        return

    _drain_already_replayed(queue, _replayed_node_names(snapshot))

    await _forward_live_events(websocket, job_id, queue, user.id)


def _drain_already_replayed(
    queue: "asyncio.Queue[AgentStreamEvent]", covered: set[str]
) -> None:
    """
    Discard any already-replayed node's event sitting in ``queue``.

    Called once, right before entering ``_forward_live_events``'s main
    loop, to resolve the (harmless, opposite-direction) race the
    subscribe-before-fetch ordering in ``stream_analysis_progress``
    introduces: a node that completes between ``subscribe()`` and the
    snapshot fetch publishes into the queue AND is captured by that same
    snapshot's replay, so without this it would be shown to the client
    twice. Non-blocking -- ``asyncio.Queue.get_nowait()`` never awaits,
    so this cannot itself introduce a new window for a live event to be
    missed. Any event whose ``agent`` is NOT in ``covered`` (a node that
    raced ahead even further than the snapshot captured) is kept, in
    original order, so genuinely new progress is never discarded.

    Args:
        queue:   This connection's broadcaster subscriber queue.
        covered: Node names already represented in the replay just sent
            (``_replayed_node_names(snapshot)``).
    """
    kept: list[AgentStreamEvent] = []
    while not queue.empty():
        try:
            event = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if event["agent"] not in covered:
            kept.append(event)
    for event in kept:
        queue.put_nowait(event)


async def _catch_up_if_already_terminal(
    job_id: uuid.UUID, user_id: uuid.UUID
) -> "AgentStreamEvent | None":
    """
    Re-check PostgreSQL for a terminal status the live stream never
    reported, and build the correct terminal event if so.

    Called from ``_forward_live_events``'s heartbeat path -- see that
    call site's BUGFIX note for why this exists: a live client can, in
    rare cases, never receive the one broadcast event that would have
    told it the job finished, leaving it stuck indefinitely even though
    the job genuinely completed. This is the self-healing half of that
    fix -- a fresh, narrowly-scoped DB read (mirroring
    ``stream_analysis_progress``'s own initial snapshot fetch and
    ownership check) run once per heartbeat interval, cheap enough to
    not matter at that cadence (default every 10s, only while otherwise
    idle) and never a source of truth divergence, since it reads the
    exact same ``get_analysis_status`` every other status surface in
    this codebase does.

    Args:
        job_id:  UUID of the analysis job.
        user_id: The authenticated caller's id, for the same ownership
            scoping every other lookup in this router applies.

    Returns:
        None if the job is not (yet) terminal, or no longer exists for
        this user (both treated as "nothing to catch up on" -- an
        ownership change mid-stream is not this function's concern).
        Otherwise the same terminal ``AgentStreamEvent``
        ``_snapshot_to_events`` would have produced as its last replayed
        event for this snapshot.
    """
    async with AsyncSessionLocal() as session:
        snapshot = await get_analysis_status(session, job_id=job_id, user_id=user_id)

    if snapshot is None or snapshot.status not in TERMINAL_STATUSES:
        return None

    last_node = "pipeline"
    if snapshot.completed_nodes:
        last_node = snapshot.completed_nodes[-1]

    return cast_event(
        job_id=str(job_id),
        agent=last_node,
        status=snapshot.status,
        output_preview=snapshot.error_message or snapshot.current_phase,
        progress_percent=snapshot.progress_percent,
        is_final=True,
    )


async def _forward_live_events(
    websocket: WebSocket,
    job_id: uuid.UUID,
    queue: "asyncio.Queue[AgentStreamEvent]",
    user_id: uuid.UUID,
) -> None:
    """
    Forward events from ``queue`` until the final one, then unsubscribe.

    ``queue`` is created by ``stream_analysis_progress`` via
    ``subscribe()`` BEFORE the DB round-trip and replay send (see that
    call site's BUGFIX note on why the subscribe timing moved) -- this
    function no longer subscribes itself, but still owns the pairing's
    other half: it guarantees ``unsubscribe`` runs on every exit path
    (normal completion, client disconnect, or any other exception) via
    the same ``try``/``finally`` as before, so a job_id can never
    accumulate a leaked subscriber for the lifetime of the process.

    Also pushes a lightweight heartbeat event (see
    ``_HEARTBEAT_AFTER_TICKS``) whenever real node-completion events
    stop arriving for too long -- e.g. an agent stuck retrying against
    a rate-limited LLM provider -- so the socket is never silent long
    enough for a router/proxy/browser idle-connection timeout to close
    it out from under a still-healthy pipeline.

    BUGFIX (root cause of the "Connection closed unexpectedly (code
    1006)" report): the disconnect probe below used to be a fresh
    ``asyncio.wait_for(websocket.receive(), timeout=0.01)`` call made
    on EVERY poll tick, cancelling the underlying ``receive()`` the
    instant it timed out (which, with no client ever sending anything
    on this server-push-only stream, was every single tick). Starlette/
    uvicorn's ``receive()`` is a resumable, stateful awaitable --
    conceptually the same kind of object an async generator's
    ``__anext__()`` is (see ``backend.routers.chat_stream``'s own
    ``_turn_loop`` comment on ``token_iter.__anext__()`` for the
    identical lesson, already learned and fixed there for the LLM
    token stream, but never applied to this receive-based probe until
    now). Cancelling it mid-flight, repeatedly, corrupts the
    connection's receive state badly enough that uvicorn tears the
    socket down itself -- observed by the client as an abnormal
    closure, WebSocket close code 1006, typically within the first
    couple of idle poll ticks (i.e. as soon as one agent takes longer
    than ``_QUEUE_POLL_INTERVAL_SECONDS`` to finish, which is the
    common case, not the exception). The fix: keep exactly ONE
    ``receive()`` call in flight for the whole streaming loop, polled
    non-destructively via ``asyncio.wait(..., timeout=...)`` (which
    never cancels on timeout) alongside the broadcaster queue, and only
    actually cancel it once, in the ``finally`` block, when the
    connection is already being torn down for good.

    Args:
        websocket: The accepted, already-authenticated connection.
        job_id:    UUID of the analysis job to stream.
        queue:     This connection's already-registered subscriber
                   queue, from ``subscribe(str(job_id))``.
        user_id:   The authenticated caller's id -- threaded through
                   only so the heartbeat's catch-up check
                   (``_catch_up_if_already_terminal``) can re-run the
                   same ownership-scoped status lookup
                   ``stream_analysis_progress`` already did once, rather
                   than a second, unscoped query.
    """
    idle_ticks = 0
    last_progress_percent = 0

    # Single, persistent receive() call used only to detect a
    # client-initiated disconnect -- see the BUGFIX note above for why
    # this must never be cancelled mid-flight.
    disconnect_task: "asyncio.Task[object]" = asyncio.ensure_future(websocket.receive())

    try:
        while True:
            # asyncio.Queue.get() (unlike websocket.receive()) is
            # always safe to create fresh and cancel every tick -- it
            # has no persistent protocol state to corrupt, just a
            # waiter that gets removed from the queue's internal list.
            queue_task: "asyncio.Task[AgentStreamEvent]" = asyncio.ensure_future(
                queue.get()
            )

            done, _pending = await asyncio.wait(
                {queue_task, disconnect_task},
                timeout=_QUEUE_POLL_INTERVAL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                queue_task.cancel()
                if _is_real_disconnect(disconnect_task):
                    return
                # A benign, unexpected client message -- this endpoint
                # defines no client->server protocol, so it is ignored.
                # Start listening for the NEXT inbound message and fall
                # through to the normal idle/heartbeat bookkeeping below
                # (the queue event, if any, has not necessarily arrived
                # yet).
                disconnect_task = asyncio.ensure_future(websocket.receive())

            if queue_task not in done:
                idle_ticks += 1
                if idle_ticks >= _HEARTBEAT_AFTER_TICKS:
                    idle_ticks = 0

                    # BUGFIX (found during live end-to-end verification):
                    # a genuine analysis run that completed exactly the
                    # normal way -- every node's own _run_broadcast fired,
                    # no exception anywhere -- was still observed to leave
                    # a live client stuck well short of 100%, forever,
                    # even though PostgreSQL already showed
                    # status='completed'. The broadcaster mechanism
                    # itself is sound in isolation (verified directly:
                    # publish/subscribe/deliver all work correctly once
                    # the event loop gets a tick to run the
                    # call_soon_threadsafe callback), so this is most
                    # likely a single lost/delayed delivery for
                    # whichever event happened to be in flight -- an
                    # inherent risk of a fire-and-forget, at-most-once
                    # broadcast with no redelivery, not something a
                    # targeted timing fix can fully rule out. Rather than
                    # keep chasing the exact trigger, this closes the
                    # failure mode itself: every heartbeat tick (already
                    # the mechanism that keeps an idle-but-healthy
                    # connection alive) now also re-checks the job's real
                    # PostgreSQL status. If it is already terminal but
                    # this connection never got told (the exact symptom
                    # above), send the correct terminal event now instead
                    # of another generic "still working" placeholder, and
                    # close -- capping the worst case UI staleness at one
                    # heartbeat interval (_HEARTBEAT_AFTER_TICKS *
                    # _QUEUE_POLL_INTERVAL_SECONDS) instead of forever.
                    catch_up_event = await _catch_up_if_already_terminal(
                        job_id, user_id
                    )
                    if catch_up_event is not None:
                        try:
                            await websocket.send_json(catch_up_event)
                        except Exception:
                            return
                        if catch_up_event["is_final"]:
                            await websocket.close(code=1000)
                            return
                        last_progress_percent = catch_up_event["progress_percent"]
                        continue

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

            event = queue_task.result()
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
        if not disconnect_task.done():
            disconnect_task.cancel()
        await unsubscribe(str(job_id), queue)


def _is_real_disconnect(disconnect_task: "asyncio.Task[object]") -> bool:
    """
    Classify a completed ``websocket.receive()`` task.

    Returns:
        True if this represents an actual client disconnect (a
        ``{"type": "websocket.disconnect"}`` ASGI message, a raised
        ``WebSocketDisconnect``, or any other receive-path failure that
        leaves the connection in an unusable state -- safer to treat
        as "gone" than to keep forwarding to it). False for a benign,
        unexpected client message that should simply be ignored on
        this server-push-only stream.
    """
    try:
        message = disconnect_task.result()
    except WebSocketDisconnect:
        return True
    except Exception:
        return True
    return bool(
        isinstance(message, dict) and message.get("type") == "websocket.disconnect"
    )
