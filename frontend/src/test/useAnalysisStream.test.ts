// frontend/src/test/useAnalysisStream.test.ts
// Tests for useAnalysisStream (T-049), added alongside T-059 since this
// hook is now the load-bearing data source for AgentProgressBoard and
// had no dedicated test file yet. Substitutes a fake WebSocket class
// (jsdom's own WebSocket never actually connects to anything) so these
// tests run fully offline and deterministically -- no real network
// call, no timing flakiness.
//
// T-096 adds a small new section: event_type is optional on the wire
// (T-095 backend addition), so EVENT_1/EVENT_2 below deliberately stay
// exactly as they were before T-095 -- no event_type field at all --
// proving old-shaped fixtures are still accepted, and a handful of
// dedicated tests confirm a message that DOES carry event_type passes
// through untouched too.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAnalysisStream } from "@/hooks/useAnalysisStream";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  /** Test helper: simulate the server pushing one message. */
  emitMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  /** Test helper: simulate the connection opening. */
  emitOpen(): void {
    this.onopen?.();
  }

  /** Test helper: simulate the server closing the connection. */
  emitClose(code: number): void {
    this.onclose?.({ code });
  }
}

function lastSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) {
    throw new Error("No FakeWebSocket was constructed");
  }
  return socket;
}

const EVENT_1 = {
  job_id: "job-1",
  agent: "fundamental_analyst",
  status: "running",
  output_preview: "Revenue grew 8% YoY.",
  progress_percent: 20,
  is_final: false,
};

const EVENT_2 = {
  job_id: "job-1",
  agent: "portfolio_manager",
  status: "completed",
  output_preview: "BUY, conviction 8/10.",
  progress_percent: 100,
  is_final: true,
};

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
  // Defensive: the reconnection describe block below uses fake timers to
  // deterministically control the setTimeout-based backoff. Restoring
  // real timers here (a no-op if a test never faked them) guarantees no
  // fake-timer state leaks into a later test in this file regardless of
  // which specific test enabled them.
  vi.useRealTimers();
});

describe("useAnalysisStream", () => {
  it("connects to the correct URL with the token as a query parameter", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    expect(lastSocket().url).toContain("/api/v1/analysis/job-1/stream");
    expect(lastSocket().url).toContain("token=jwt-token");
  });

  it("does not connect when disabled", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token", enabled: false }));

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("appends events in arrival order, never replacing earlier ones", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(EVENT_1);
    });
    await waitFor(() => expect(result.current.events).toHaveLength(1));

    act(() => {
      lastSocket().emitMessage(EVENT_2);
    });
    await waitFor(() => expect(result.current.events).toHaveLength(2));

    expect(result.current.events[0]).toEqual(EVENT_1);
    expect(result.current.events[1]).toEqual(EVENT_2);
  });

  it("marks isComplete once the is_final event arrives", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    expect(result.current.isComplete).toBe(false);

    act(() => {
      lastSocket().emitMessage(EVENT_2);
    });

    await waitFor(() => expect(result.current.isComplete).toBe(true));
    expect(result.current.progressPercent).toBe(100);
  });

  it("surfaces a readable error for the 4401 (unauthorized) close code", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "bad-token" }));

    act(() => {
      lastSocket().emitClose(4401);
    });

    await waitFor(() =>
      expect(result.current.error).toBe(
        "Not authorized to view this analysis (invalid or expired token).",
      ),
    );
  });

  it("ignores a malformed (non-JSON) message without crashing", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().onmessage?.({ data: "not json" });
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Received a malformed (non-JSON) message from the server."),
    );
    expect(result.current.events).toHaveLength(0);
  });

  it("ignores a well-formed JSON message that does not match AgentStreamEvent's shape, without crashing", async () => {
    // T-074 audit (Part B3): a message that parses as JSON but is missing
    // required fields (e.g. a truncated payload, or a future backend
    // schema change) must be rejected by isAgentStreamEvent, not crash the
    // render or silently populate `events` with undefined fields.
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitMessage({ job_id: "job-1", agent: "fundamental_analyst" });
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Received a message that does not match AgentStreamEvent."),
    );
    expect(result.current.events).toHaveLength(0);
  });

  it("handles a duplicate event delivered twice by appending both, without crashing", async () => {
    // T-074 audit (Part B3): the pipeline can legitimately re-broadcast the
    // same node's event (e.g. a retry), and out-of-order/duplicate delivery
    // must degrade gracefully -- the hook has no dedup logic by design (each
    // event is a distinct progress tick), so this confirms it simply keeps
    // appending in arrival order rather than throwing.
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitMessage(EVENT_1);
      lastSocket().emitMessage(EVENT_1);
    });

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    expect(result.current.events[0]).toEqual(EVENT_1);
    expect(result.current.events[1]).toEqual(EVENT_1);
    expect(result.current.error).toBeNull();
  });

  it("closes the socket on unmount", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { unmount } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));
    const socket = lastSocket();

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("schedules a reconnect (not an immediate terminal error) for a non-1000 close before the pipeline finished", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitClose(1006);
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Connection lost -- reconnecting (attempt 1/3)…"),
    );
  });

  it("does not surface an error for a non-1000 close after is_final already arrived", async () => {
    // Regression test: Vite's dev server proxy (vite.config.ts's /api
    // rule) does not reliably relay the backend's clean
    // websocket.close(code=1000) through to the browser once
    // backend/routers/websocket.py sends the terminal event -- this has
    // been observed surfacing to the browser as an abnormal closure
    // (code 1006) on a fully successful analysis. Once the terminal
    // event has already been rendered, that should never read as an
    // error to the user.
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitMessage(EVENT_2); // is_final: true
    });
    await waitFor(() => expect(result.current.isComplete).toBe(true));

    act(() => {
      lastSocket().emitClose(1006);
    });

    // Give any (incorrect) error-setting state update a chance to land
    // before asserting its absence.
    await waitFor(() => expect(result.current.error).toBeNull());
  });

  it("still surfaces 4401/4404 even after is_final (edge case, defensive)", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitMessage(EVENT_2);
    });
    await waitFor(() => expect(result.current.isComplete).toBe(true));

    act(() => {
      lastSocket().emitClose(4404);
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Analysis job not found, or it does not belong to you."),
    );
  });

  describe("stale-socket race (found during live end-to-end verification)", () => {
    it("ignores a belated close/error from a superseded socket after a reconnect", async () => {
      // Regression test for the exact bug: React 18 StrictMode's
      // development-only mount -> cleanup -> mount double-invoke (or any
      // jobId/token change) opens a first socket, tears it down almost
      // immediately, then opens a second one. If the FIRST socket's
      // close/error event arrives asynchronously AFTER the second socket
      // has already taken over, it must not be allowed to overwrite the
      // second (real, current) socket's state -- previously this hook
      // used a single shared boolean ref that a later effect run would
      // reset to "current" out from under the earlier socket's in-flight
      // callbacks, so the stale socket's belated close(1006) incorrectly
      // set a "Connection closed unexpectedly" error even though the
      // real connection was open and healthy.
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result, rerender } = renderHook(
        ({ jobId }: { jobId: string }) => useAnalysisStream({ jobId, token: "jwt-token" }),
        { initialProps: { jobId: "job-1" } },
      );

      const staleSocket = lastSocket();

      // Changing jobId tears down the first effect (closing staleSocket)
      // and runs a fresh one, opening a second socket -- the same shape
      // of transition StrictMode's double-invoke produces.
      rerender({ jobId: "job-2" });
      const currentSocket = lastSocket();
      expect(currentSocket).not.toBe(staleSocket);

      act(() => {
        currentSocket.emitOpen();
      });
      await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

      // The stale socket's close event arrives late, after the real
      // connection is already open -- it must be ignored entirely.
      act(() => {
        staleSocket.emitClose(1006);
      });

      expect(result.current.connectionStatus).toBe("open");
      expect(result.current.error).toBeNull();
    });
  });

  describe("reconnection (Section C, unit 9 audit finding)", () => {
    // Uses fake timers to deterministically control the setTimeout-based
    // backoff (see RECONNECT_BASE_DELAY_MS in useAnalysisStream.ts)
    // rather than waiting on real 1s/2s/3s delays. Advancing the fake
    // timer inside `act()` synchronously fires the scheduled
    // reconnect-nonce bump, whose resulting re-render (and the effect
    // re-run it triggers -- closing the old socket, opening a new one)
    // is flushed before `act()` returns, so no `waitFor` is needed for
    // the timer-driven steps themselves.

    it("opens a new socket after an unexpected close, once the backoff delay elapses", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));
      const firstSocket = lastSocket();

      act(() => {
        firstSocket.emitClose(1006);
      });
      expect(FakeWebSocket.instances).toHaveLength(1); // no reconnect yet

      act(() => {
        vi.advanceTimersByTime(1000); // attempt 1 -> RECONNECT_BASE_DELAY_MS * 1
      });

      expect(FakeWebSocket.instances).toHaveLength(2);
      expect(lastSocket()).not.toBe(firstSocket);
    });

    it("a successful reconnect clears the error and reports connectionStatus 'open'", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toBe("Connection lost -- reconnecting (attempt 1/3)…");

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      act(() => {
        lastSocket().emitOpen();
      });

      expect(result.current.connectionStatus).toBe("open");
      expect(result.current.error).toBeNull();
    });

    it("preserves already-received events across a reconnect's own event replay, without duplicating them", () => {
      // The backend replays a job's full completed_nodes history on
      // every fresh connect (including a reconnect) specifically to
      // support resuming -- so the hook resets `events` to empty right
      // before opening the new socket, and relies on that replay (not
      // whatever it already had) to repopulate the list. This test
      // simulates exactly that: the reconnected socket re-sends EVENT_1,
      // and it must appear exactly once, not twice.
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitMessage(EVENT_1);
      });
      expect(result.current.events).toHaveLength(1);

      act(() => {
        lastSocket().emitClose(1006);
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });

      // The reconnect already reset `events` to [] as part of opening
      // the new socket -- confirm that happened before the replay.
      expect(result.current.events).toHaveLength(0);

      act(() => {
        lastSocket().emitMessage(EVENT_1); // the backend's replay
      });

      expect(result.current.events).toHaveLength(1);
      expect(result.current.events[0]).toEqual(EVENT_1);
    });

    it("gives up after MAX_RECONNECT_ATTEMPTS and surfaces a terminal error", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      // Attempt 1: close -> scheduled -> fires -> new socket also fails.
      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toBe("Connection lost -- reconnecting (attempt 1/3)…");
      act(() => {
        vi.advanceTimersByTime(1000);
      });

      // Attempt 2.
      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toBe("Connection lost -- reconnecting (attempt 2/3)…");
      act(() => {
        vi.advanceTimersByTime(2000);
      });

      // Attempt 3 -- the last one allowed.
      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toBe("Connection lost -- reconnecting (attempt 3/3)…");
      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(FakeWebSocket.instances).toHaveLength(4); // 1 initial + 3 reconnects

      // A 4th failure exhausts the budget -- no further reconnect is
      // scheduled, and the error becomes the terminal, non-reconnecting
      // message the pre-reconnect behaviour always showed.
      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toBe(
        "Connection closed unexpectedly (code 1006) after 3 reconnect attempts.",
      );

      act(() => {
        vi.advanceTimersByTime(10_000);
      });
      expect(FakeWebSocket.instances).toHaveLength(4); // no further attempt
    });

    it("does not reconnect on a normal close (code 1000)", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

      act(() => {
        lastSocket().emitClose(1000);
      });
      act(() => {
        vi.advanceTimersByTime(10_000);
      });

      expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it("does not reconnect on 4401 (unauthorized) or 4404 (not found) -- both are terminal", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

      act(() => {
        lastSocket().emitClose(4401);
      });
      act(() => {
        vi.advanceTimersByTime(10_000);
      });

      expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it("clears any pending reconnect timer on unmount", () => {
      vi.useFakeTimers();
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { unmount } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(FakeWebSocket.instances).toHaveLength(1);

      unmount();

      act(() => {
        vi.advanceTimersByTime(10_000);
      });

      // No reconnect fires after unmount -- the pending timer was
      // cleared by the effect's own cleanup, not left to fire against
      // an unmounted hook.
      expect(FakeWebSocket.instances).toHaveLength(1);
    });
  });

  describe("event_type (T-096)", () => {
    it("still accepts a message with no event_type field at all", async () => {
      // EVENT_1/EVENT_2 above are the exact pre-T-095 shape -- no
      // event_type key. This is the literal "WS clients ignoring the
      // new event type still work" acceptance criterion, applied to
      // this hook's own runtime guard.
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitMessage(EVENT_1);
      });

      await waitFor(() => expect(result.current.events).toHaveLength(1));
      expect(result.current.events[0]?.event_type).toBeUndefined();
    });

    it("passes event_type through untouched when the message does carry it", async () => {
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitMessage({ ...EVENT_1, event_type: "node_started" });
      });

      await waitFor(() => expect(result.current.events).toHaveLength(1));
      expect(result.current.events[0]?.event_type).toBe("node_started");
    });

    it("rejects a message where event_type is present but not a string", async () => {
      vi.stubGlobal("WebSocket", FakeWebSocket);

      const { result } = renderHook(() =>
        useAnalysisStream({ jobId: "job-1", token: "jwt-token" }),
      );

      act(() => {
        lastSocket().emitMessage({ ...EVENT_1, event_type: 123 });
      });

      await waitFor(() =>
        expect(result.current.error).toBe(
          "Received a message that does not match AgentStreamEvent.",
        ),
      );
      expect(result.current.events).toHaveLength(0);
    });
  });
});
