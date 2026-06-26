# backend/services/ws_broadcaster.py
"""
AIRP -- WebSocket Event Broadcaster (T-049)

In-process publish/subscribe registry that fans out one
``AgentStreamEvent``-shaped dict per LangGraph node completion to every
WebSocket client currently subscribed to that analysis job. This is what
turns the synchronous, fire-and-forget checkpoint write T-033's
``_persist_after`` already performs after every sequential node into a
live push to the browser, without the client needing to poll T-048's
GET /status endpoint.

Why in-process (no Redis pub/sub, no message broker)
------------------------------------------------------
AIRP's production deployment target (Render free tier, see
backend/main.py and docs/APIS.md) runs the FastAPI app as a single
process/instance. The LangGraph pipeline itself already executes inside
that same process -- as a ``BackgroundTasks``-scheduled coroutine
(``backend.services.analysis.run_analysis_pipeline``) dispatched to a
worker thread via ``asyncio.to_thread`` -- so a WebSocket connection
accepted by that same process can be reached with a plain in-memory
registry keyed by job_id. Reaching for Redis pub/sub (Upstash, the
project's only other available message-passing primitive) would add a
network round-trip and a free-tier command-budget cost (see the
10,000 commands/day Upstash cap documented in
backend/db/redis_client.py) to solve a multi-process fan-out problem
AIRP does not have. If a future task moves the LangGraph workers to a
separate process or horizontally scales the API, this module's
``publish_event``/``subscribe`` functions are the only call sites that
would need to swap their backing store -- every caller
(``backend.graph.nodes``, ``backend.routers.websocket``) only depends
on this module's public functions, never on the registry's internals.

Why a plain ``threading.Lock`` instead of ``asyncio.Lock``
-------------------------------------------------------------
``publish_event`` is called from inside a LangGraph node running on a
worker thread (the same thread context ``backend.graph.nodes._run_persist``
already documents -- LangGraph executes nodes via a ThreadPoolExecutor),
while ``subscribe``/``unsubscribe`` run on FastAPI's main event loop in
the main thread. ``asyncio.Lock``/``asyncio.Queue`` are documented as
*not* thread-safe and are bound to whichever event loop first awaits
them -- acquiring one from a second thread (or a second ``asyncio.run()``
call, which spins up a brand-new loop each time) can raise or silently
misbehave. ``threading.Lock`` has no such restriction: it is the correct
primitive for protecting a plain dict/set that is mutated from multiple
OS threads, exactly the situation here. Each subscriber's
``asyncio.Queue`` is paired with the event loop that created it
(captured via ``asyncio.get_running_loop()`` inside ``subscribe``, which
always runs on that loop), and delivery from the worker thread uses
``loop.call_soon_threadsafe(queue.put_nowait, event)`` -- asyncio's own
documented mechanism for scheduling a thread-safe callback onto a
specific loop from any other thread.

Design
------
* ``_Subscriber`` -- pairs one ``asyncio.Queue`` with the event loop
  that owns it, so delivery from a different thread can be routed back
  onto the correct loop instead of guessing.
* ``_subscribers: dict[str, set[_Subscriber]]`` -- one set of
  subscribers per job_id. A job with zero active WebSocket connections
  has no entry at all.
* ``subscribe(job_id)`` -- called by the WebSocket route handler on
  connect (on FastAPI's event loop). Returns a fresh ``asyncio.Queue``
  already registered to receive every subsequent
  ``publish_event(job_id, ...)`` call. Unbounded queue size
  (``maxsize=0``) is intentional: a 9-phase pipeline emits at most
  ~15 events total (see backend.graph.nodes.NODE_* constants), so an
  unbounded queue can never accumulate enough items to be a real
  memory concern, and bounding it would risk silently dropping an
  agent-completion event if a slow client briefly stops reading --
  worse for a live progress viewer than a few extra dicts in memory.
* ``unsubscribe(job_id, queue)`` -- called from the route handler's
  ``finally`` block so a disconnected client's subscriber is not
  retained, and so a job's dict entry is removed entirely once its
  last subscriber leaves.
* ``publish_event(job_id, event)`` -- called from
  ``backend.graph.nodes._run_broadcast`` after every sequential node
  completes. Fans the same event dict out to every subscriber
  currently registered for job_id via ``call_soon_threadsafe``. A
  job_id with no subscribers (the common case -- most analyses run
  via T-047/T-048 polling alone, with no WebSocket client ever
  connecting) is a guaranteed no-op, not an error.
* Never raises. A bad event dict or a closed loop must never abort the
  LangGraph pipeline that is the actual product of an analysis run --
  this mirrors the project-wide "agent/node functions must never
  raise" rule and the identical fire-and-forget contract
  backend.services.state_persistence.persist_state already has.

Public API
----------
    from backend.services.ws_broadcaster import (
        AgentStreamEvent,
        subscribe,
        unsubscribe,
        publish_event,
        cast_event,
        TERMINAL_STATUSES,
    )
"""

import asyncio
from dataclasses import dataclass
import logging
import threading
from typing import TypedDict

logger = logging.getLogger(__name__)

__all__ = [
    "AgentStreamEvent",
    "subscribe",
    "unsubscribe",
    "publish_event",
    "cast_event",
    "TERMINAL_STATUSES",
]

# ---------------------------------------------------------------------------
# Event shape
# ---------------------------------------------------------------------------


class AgentStreamEvent(TypedDict):
    """
    One push payload sent over WS /api/v1/analysis/{job_id}/stream.

    Matches the T-049 acceptance criterion's literal shape verbatim --
    ``{agent, status, output_preview}`` -- plus three fields needed to
    make the stream self-describing without a second GET /status call:
    ``job_id`` (so a client subscribed to multiple jobs in one tab can
    route events correctly), ``progress_percent`` (reuses
    backend.services.analysis.compute_progress -- no new progress logic,
    per the T-048 doc's own "next task" note), and ``is_final`` (True
    exactly once, on the event that causes the server to close the
    socket -- see backend.routers.websocket).
    """

    job_id: str
    agent: str
    status: str
    output_preview: str
    progress_percent: int
    is_final: bool


def cast_event(
    job_id: str,
    agent: str,
    status: str,
    output_preview: str,
    progress_percent: int,
    is_final: bool,
) -> AgentStreamEvent:
    """
    Construct an ``AgentStreamEvent`` dict with every field explicit.

    A thin, explicitly-typed constructor (rather than building the
    TypedDict as a bare literal at each call site) so
    ``backend.graph.nodes`` and ``backend.routers.websocket`` -- the
    two call sites that build outgoing events -- cannot accidentally
    typo a key name or omit a field; mypy --strict checks every keyword
    argument here against ``AgentStreamEvent``'s declared fields.

    Args:
        job_id:           UUID string of the analysis job.
        agent:            LangGraph node name that just completed
                           (e.g. 'fundamental_analyst', 'pdf_export').
        status:           Pipeline lifecycle status at the moment this
                           node completed -- 'running', 'completed', or
                           'failed'.
        output_preview:   Short human-readable summary of what this
                           node produced (or its error) -- see
                           backend.graph.nodes._build_output_preview.
        progress_percent: 0-100, computed via the same
                           backend.services.analysis.compute_progress
                           T-048 already uses for GET /status, so the
                           live stream and the poll endpoint can never
                           disagree about how far along a job is.
        is_final:         True exactly once per job -- on the event
                           that should cause the WebSocket route
                           handler to close the connection.

    Returns:
        A fully-populated AgentStreamEvent ready for publish_event.
    """
    return AgentStreamEvent(
        job_id=job_id,
        agent=agent,
        status=status,
        output_preview=output_preview,
        progress_percent=progress_percent,
        is_final=is_final,
    )


#: Pipeline lifecycle statuses that mean "no further events will ever
#: be published for this job_id" -- the server-side close condition
#: backend.routers.websocket checks after every event it forwards.
#: Mirrors backend.services.analysis.AnalysisStatusResult.status's two
#: terminal values; 'pending' and 'running' are deliberately excluded.
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})

# ---------------------------------------------------------------------------
# Module-level subscriber registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Subscriber:
    """
    One WebSocket connection's delivery target.

    Pairs the ``asyncio.Queue`` the route handler reads from with the
    event loop that created it (always FastAPI's main event loop,
    captured via ``asyncio.get_running_loop()`` inside ``subscribe``).
    ``publish_event`` -- which may run on a completely different
    thread with no event loop of its own -- uses ``loop`` to schedule
    delivery back onto the correct loop via ``call_soon_threadsafe``,
    rather than touching ``queue`` directly from the wrong thread.
    """

    queue: "asyncio.Queue[AgentStreamEvent]"
    loop: asyncio.AbstractEventLoop


#: One _Subscriber per active WebSocket connection, grouped by job_id.
#: A job_id key is created on first subscribe() and deleted once its
#: last subscriber unsubscribe()s -- never grows unboundedly across
#: the process lifetime.
_subscribers: dict[str, set[_Subscriber]] = {}

#: Guards every read/mutation of ``_subscribers``. A plain
#: threading.Lock (NOT asyncio.Lock) because this dict is touched from
#: two different OS threads: FastAPI's main event loop thread
#: (subscribe/unsubscribe) and whichever worker thread LangGraph is
#: currently running a node on (publish_event) -- see this module's
#: docstring for why asyncio.Lock is unsafe here. Every critical
#: section below is a handful of dict/set operations with no I/O and
#: no ``await``, so a short-held plain lock never blocks the event
#: loop for a perceptible amount of time.
_registry_lock = threading.Lock()


async def subscribe(job_id: str) -> "asyncio.Queue[AgentStreamEvent]":
    """
    Register a new subscriber queue for ``job_id`` and return it.

    Called once per accepted WebSocket connection
    (backend.routers.websocket.stream_analysis_progress), immediately
    after the connection's ownership check passes. Must be called from
    a coroutine running on the event loop that will later read from
    the returned queue (true for any normal FastAPI route handler).

    Args:
        job_id: UUID string of the analysis job to listen to.

    Returns:
        A fresh, empty ``asyncio.Queue`` already registered to receive
        future events for this job_id.
    """
    queue: "asyncio.Queue[AgentStreamEvent]" = asyncio.Queue()
    loop = asyncio.get_running_loop()
    subscriber = _Subscriber(queue=queue, loop=loop)

    with _registry_lock:
        _subscribers.setdefault(job_id, set()).add(subscriber)
        count = len(_subscribers[job_id])

    logger.debug(
        "ws_broadcaster.subscribe: job_id=%s now has %d subscriber(s)",
        job_id,
        count,
    )
    return queue


async def unsubscribe(job_id: str, queue: "asyncio.Queue[AgentStreamEvent]") -> None:
    """
    Remove the subscriber holding ``queue`` from ``job_id``'s set.

    Called from the WebSocket route handler's ``finally`` block on
    every disconnect path (clean close, client-initiated disconnect, or
    an exception propagating out of the receive loop) so a closed
    socket's subscriber is never retained. When this was the job's
    last remaining subscriber, the job_id key itself is deleted -- a
    completed analysis with no one watching leaves no trace in this
    module's memory.

    Safe to call even if ``queue`` was already removed or if ``job_id``
    has no entry at all -- both are silently treated as
    already-unsubscribed rather than raising, since "stop listening" is
    idempotent by nature.

    Args:
        job_id: UUID string of the analysis job.
        queue:  The exact queue instance returned by ``subscribe``.
    """
    with _registry_lock:
        subscribers = _subscribers.get(job_id)
        if subscribers is None:
            return
        remaining = {s for s in subscribers if s.queue is not queue}
        if remaining:
            _subscribers[job_id] = remaining
        else:
            _subscribers.pop(job_id, None)

    logger.debug("ws_broadcaster.unsubscribe: job_id=%s", job_id)


def publish_event(job_id: str, event: AgentStreamEvent) -> None:
    """
    Publish ``event`` to every WebSocket subscriber of ``job_id``.

    Safe to call from any thread, with or without a running event loop
    in the calling thread -- exactly the context
    ``backend.graph.nodes._run_broadcast`` calls this from (a LangGraph
    node executing on a worker thread, the same constraint
    ``backend.graph.nodes._run_persist`` already documents for
    persistence). For each registered subscriber, delivery is
    scheduled onto *that subscriber's own* event loop via
    ``loop.call_soon_threadsafe(queue.put_nowait, event)`` -- asyncio's
    documented thread-safe scheduling primitive -- rather than calling
    ``queue.put_nowait`` directly from this (possibly foreign) thread.

    Never raises: a job_id with no subscribers is a normal, frequent
    case (most analyses run via T-047/T-048 polling alone, with no
    WebSocket client ever connecting) and must resolve to a silent
    no-op, not an error; a subscriber whose loop has already closed
    (e.g. the client disconnected and FastAPI tore down its connection
    handler in the instant between the lock release above and this
    call) is caught and logged per-subscriber so one stale subscriber
    can never prevent delivery to the others, and can never abort the
    LangGraph pipeline that is the actual product of an analysis run.

    Args:
        job_id: UUID string of the analysis job this event belongs to.
        event:  The AgentStreamEvent to deliver.
    """
    with _registry_lock:
        subscribers = list(_subscribers.get(job_id, ()))

    for subscriber in subscribers:
        try:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)
        except Exception as exc:
            logger.error(
                "ws_broadcaster.publish_event: failed to schedule delivery "
                "for job_id=%s agent=%s: %s",
                job_id,
                event.get("agent", "<unknown>"),
                exc,
            )


# ---------------------------------------------------------------------------
# Test-only helpers (not part of the public API)
# ---------------------------------------------------------------------------


def _subscriber_count_for_testing(job_id: str) -> int:
    """
    Return the number of active subscribers for ``job_id``.

    Test-only helper so unit tests can assert on registry state without
    reaching into the private ``_subscribers`` dict directly from
    outside this module.
    """
    with _registry_lock:
        return len(_subscribers.get(job_id, ()))


def _reset_for_testing() -> None:
    """
    Clear the entire subscriber registry.

    Test-only helper. The registry is module-level (process-wide)
    state, so without an explicit reset between tests, a subscriber
    left registered by one test could receive events published by
    another test running later in the same pytest process -- this
    guards against that cross-test leakage.
    """
    with _registry_lock:
        _subscribers.clear()
