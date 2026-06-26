# backend/tests/unit/test_ws_broadcaster.py
"""
Unit tests for T-049: backend/services/ws_broadcaster.py

Acceptance criteria (from project plan, T-049):
  - WebSocket sends event per agent completion
  - frontend receives and displays in order
  - connection closes cleanly

This file covers the in-process pub/sub registry in isolation (no
FastAPI, no WebSocket, no DB) -- the WebSocket route handler itself is
covered separately in test_websocket_router.py, and the
backend.graph.nodes integration (_run_broadcast, _build_output_preview)
is covered in test_ws_broadcast_nodes.py.

Test strategy
-------------
  1. cast_event           -- builds a fully-populated, correctly-typed
                              AgentStreamEvent
  2. subscribe / unsubscribe -- registry bookkeeping (count goes up/down,
                              job_id key created/removed at the right times)
  3. publish_event        -- delivers to every subscriber of a job_id,
                              in order, and is a silent no-op for a
                              job_id with zero subscribers
  4. Multiple subscribers -- the same job_id can have more than one
                              listener and all receive every event
  5. Cross-job isolation  -- an event published for job A never reaches
                              a subscriber of job B
  6. Error tolerance      -- publish_event never raises even if a
                              subscriber's loop is already closed
  7. TERMINAL_STATUSES    -- contains exactly 'completed' and 'failed'

All tests run on the real asyncio event loop (asyncio.run / pytest-asyncio)
since this module's entire job is to coordinate real asyncio.Queue /
event-loop scheduling -- mocking those away would test nothing.
ENVIRONMENT must be set to 'test' before any backend import (enforced by
backend.tests.conftest's autouse require_test_environment fixture).
"""

import asyncio
from collections.abc import Generator

import pytest

from backend.services.ws_broadcaster import (
    TERMINAL_STATUSES,
    AgentStreamEvent,
    _reset_for_testing,
    _subscriber_count_for_testing,
    cast_event,
    publish_event,
    subscribe,
    unsubscribe,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    """
    Reset the module-level subscriber registry before and after every
    test in this file.

    The registry is process-wide state (see ws_broadcaster.py's own
    docstring), so without this, a subscriber left registered by one
    test could receive events published by a later test in the same
    pytest run -- this fixture guarantees every test starts and ends
    with an empty registry regardless of test ordering.
    """
    _reset_for_testing()
    yield
    _reset_for_testing()


def _make_event(
    job_id: str = "job-1",
    agent: str = "fundamental_analyst",
    status: str = "running",
    output_preview: str = "Score 8/10",
    progress_percent: int = 40,
    is_final: bool = False,
) -> AgentStreamEvent:
    """Build a sample AgentStreamEvent for tests that don't care about
    the exact field values, only that an event was delivered."""
    return cast_event(
        job_id=job_id,
        agent=agent,
        status=status,
        output_preview=output_preview,
        progress_percent=progress_percent,
        is_final=is_final,
    )


# ---------------------------------------------------------------------------
# 1. cast_event
# ---------------------------------------------------------------------------


class TestCastEvent:
    def test_builds_event_with_all_fields(self) -> None:
        event = cast_event(
            job_id="job-123",
            agent="risk_officer",
            status="running",
            output_preview="Risk score 4/10",
            progress_percent=70,
            is_final=False,
        )
        assert event == {
            "job_id": "job-123",
            "agent": "risk_officer",
            "status": "running",
            "output_preview": "Risk score 4/10",
            "progress_percent": 70,
            "is_final": False,
        }

    def test_is_final_true_is_preserved(self) -> None:
        event = cast_event(
            job_id="job-1",
            agent="pdf_export",
            status="completed",
            output_preview="PDF exported",
            progress_percent=100,
            is_final=True,
        )
        assert event["is_final"] is True


# ---------------------------------------------------------------------------
# 2. subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_returns_a_queue(self) -> None:
        queue = await subscribe("job-1")
        assert isinstance(queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_subscribe_registers_one_subscriber(self) -> None:
        await subscribe("job-1")
        assert _subscriber_count_for_testing("job-1") == 1

    @pytest.mark.asyncio
    async def test_second_subscribe_same_job_increments_count(self) -> None:
        await subscribe("job-1")
        await subscribe("job-1")
        assert _subscriber_count_for_testing("job-1") == 2

    @pytest.mark.asyncio
    async def test_subscribe_different_jobs_independent_counts(self) -> None:
        await subscribe("job-1")
        await subscribe("job-2")
        await subscribe("job-2")
        assert _subscriber_count_for_testing("job-1") == 1
        assert _subscriber_count_for_testing("job-2") == 2

    @pytest.mark.asyncio
    async def test_unsubscribed_job_has_zero_subscribers(self) -> None:
        assert _subscriber_count_for_testing("never-subscribed-job") == 0


class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_the_subscriber(self) -> None:
        queue = await subscribe("job-1")
        await unsubscribe("job-1", queue)
        assert _subscriber_count_for_testing("job-1") == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_leaves_other_subscribers_intact(self) -> None:
        queue_a = await subscribe("job-1")
        await subscribe("job-1")
        await unsubscribe("job-1", queue_a)
        assert _subscriber_count_for_testing("job-1") == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_job_id_does_not_raise(self) -> None:
        queue: "asyncio.Queue[AgentStreamEvent]" = asyncio.Queue()
        await unsubscribe("job-that-does-not-exist", queue)

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_queue_does_not_raise(self) -> None:
        await subscribe("job-1")
        foreign_queue: "asyncio.Queue[AgentStreamEvent]" = asyncio.Queue()
        await unsubscribe("job-1", foreign_queue)
        # The real subscriber is untouched.
        assert _subscriber_count_for_testing("job-1") == 1

    @pytest.mark.asyncio
    async def test_double_unsubscribe_is_idempotent(self) -> None:
        queue = await subscribe("job-1")
        await unsubscribe("job-1", queue)
        await unsubscribe("job-1", queue)
        assert _subscriber_count_for_testing("job-1") == 0


# ---------------------------------------------------------------------------
# 3. publish_event -- delivery and no-subscriber no-op
# ---------------------------------------------------------------------------


class TestPublishEventDelivery:
    @pytest.mark.asyncio
    async def test_subscriber_receives_published_event(self) -> None:
        queue = await subscribe("job-1")
        event = _make_event(job_id="job-1")

        publish_event("job-1", event)
        # publish_event schedules delivery via call_soon_threadsafe;
        # yield control once so the scheduled callback actually runs.
        await asyncio.sleep(0)

        received = queue.get_nowait()
        assert received == event

    @pytest.mark.asyncio
    async def test_events_are_received_in_publish_order(self) -> None:
        queue = await subscribe("job-1")
        first = _make_event(job_id="job-1", agent="fundamental_analyst")
        second = _make_event(job_id="job-1", agent="technical_analyst")
        third = _make_event(job_id="job-1", agent="research_join")

        publish_event("job-1", first)
        publish_event("job-1", second)
        publish_event("job-1", third)
        await asyncio.sleep(0)

        assert queue.get_nowait()["agent"] == "fundamental_analyst"
        assert queue.get_nowait()["agent"] == "technical_analyst"
        assert queue.get_nowait()["agent"] == "research_join"

    @pytest.mark.asyncio
    async def test_publish_with_no_subscribers_does_not_raise(self) -> None:
        event = _make_event(job_id="job-with-nobody-listening")
        publish_event("job-with-nobody-listening", event)
        await asyncio.sleep(0)
        # No assertion needed beyond "did not raise" -- this IS the test.

    @pytest.mark.asyncio
    async def test_publish_before_any_subscribe_is_a_silent_no_op(self) -> None:
        event = _make_event(job_id="job-1")
        publish_event("job-1", event)
        await asyncio.sleep(0)
        assert _subscriber_count_for_testing("job-1") == 0


class TestPublishEventMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_all_subscribers_of_same_job_receive_the_event(self) -> None:
        queue_a = await subscribe("job-1")
        queue_b = await subscribe("job-1")
        event = _make_event(job_id="job-1")

        publish_event("job-1", event)
        await asyncio.sleep(0)

        assert queue_a.get_nowait() == event
        assert queue_b.get_nowait() == event


class TestPublishEventCrossJobIsolation:
    @pytest.mark.asyncio
    async def test_event_for_job_a_does_not_reach_job_b_subscriber(self) -> None:
        queue_b = await subscribe("job-b")
        await subscribe("job-a")
        event = _make_event(job_id="job-a")

        publish_event("job-a", event)
        await asyncio.sleep(0)

        assert queue_b.empty()


# ---------------------------------------------------------------------------
# 4. Error tolerance -- publish_event never raises
# ---------------------------------------------------------------------------


class TestPublishEventErrorTolerance:
    @pytest.mark.asyncio
    async def test_publish_swallows_a_subscriber_with_closed_loop(self) -> None:
        """
        A subscriber whose loop.call_soon_threadsafe raises (e.g. the
        loop was already closed) must not prevent delivery to OTHER
        subscribers of the same job_id, and must not raise out of
        publish_event itself -- mirrors the fire-and-forget contract
        backend.graph.nodes._run_persist already has for persistence
        failures.
        """
        good_queue = await subscribe("job-1")

        # Manually register a second subscriber whose loop is a stand-in
        # that raises when scheduling -- simulates a closed event loop
        # without actually closing the real test loop out from under us.
        from typing import cast

        from backend.services import ws_broadcaster as mod

        class _DeadLoop:
            def call_soon_threadsafe(self, *args: object) -> None:
                raise RuntimeError("Event loop is closed")

        bad_subscriber = mod._Subscriber(
            queue=asyncio.Queue(),
            loop=cast(asyncio.AbstractEventLoop, _DeadLoop()),
        )
        with mod._registry_lock:
            mod._subscribers.setdefault("job-1", set()).add(bad_subscriber)

        event = _make_event(job_id="job-1")
        publish_event("job-1", event)  # must not raise
        await asyncio.sleep(0)

        assert good_queue.get_nowait() == event


# ---------------------------------------------------------------------------
# 5. TERMINAL_STATUSES
# ---------------------------------------------------------------------------


class TestTerminalStatuses:
    def test_contains_completed_and_failed(self) -> None:
        assert TERMINAL_STATUSES == frozenset({"completed", "failed"})

    def test_does_not_contain_pending_or_running(self) -> None:
        assert "pending" not in TERMINAL_STATUSES
        assert "running" not in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# 6. Public API
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_all_exports_present(self) -> None:
        from backend.services import ws_broadcaster

        for name in ws_broadcaster.__all__:
            assert hasattr(ws_broadcaster, name)
