// frontend/src/test/useAnalysisStream.test.ts
// Tests for useAnalysisStream (T-049), added alongside T-059 since this
// hook is now the load-bearing data source for AgentProgressBoard and
// had no dedicated test file yet. Substitutes a fake WebSocket class
// (jsdom's own WebSocket never actually connects to anything) so these
// tests run fully offline and deterministically -- no real network
// call, no timing flakiness.

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

  it("closes the socket on unmount", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { unmount } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));
    const socket = lastSocket();

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("surfaces an error for a non-1000 close before the pipeline finished", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useAnalysisStream({ jobId: "job-1", token: "jwt-token" }));

    act(() => {
      lastSocket().emitClose(1006);
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Connection closed unexpectedly (code 1006)."),
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
});
