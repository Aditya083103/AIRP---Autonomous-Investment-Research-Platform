// frontend/src/test/useChatStream.test.ts
// Tests for useChatStream (T-105). Substitutes a fake WebSocket class
// (the same approach test/useAnalysisStream.test.ts (T-049) already
// established -- jsdom's own WebSocket never actually connects to
// anything) so these tests run fully offline and deterministically.
//
// Unlike useAnalysisStream, this hook both receives AND sends over the
// socket (sendMessage), and the wire protocol has five distinct
// event_types (start/token/heartbeat/done/error) instead of one
// implicit shape -- the describe blocks below are organised around
// that turn lifecycle.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CONNECTING = 0;
  static readonly CLOSED = 3;

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
  }

  /** Test helper: simulate the server pushing one message. */
  emitMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  /** Test helper: simulate the connection opening. */
  emitOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** Test helper: simulate the server closing the connection. */
  emitClose(code: number): void {
    this.readyState = FakeWebSocket.CLOSED;
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

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function startEvent(messageId: string | null = null, analysisJobId: string | null = null): unknown {
  return {
    session_id: "session-1",
    event_type: "start",
    token: "",
    message_id: messageId,
    is_final: false,
    error: null,
    analysis_job_id: analysisJobId,
  };
}

function tokenEvent(token: string): unknown {
  return {
    session_id: "session-1",
    event_type: "token",
    token,
    message_id: null,
    is_final: false,
    error: null,
  };
}

function doneEvent(messageId: string): unknown {
  return {
    session_id: "session-1",
    event_type: "done",
    token: "",
    message_id: messageId,
    is_final: true,
    error: null,
  };
}

function errorEvent(message: string): unknown {
  return {
    session_id: "session-1",
    event_type: "error",
    token: "",
    message_id: null,
    is_final: true,
    error: message,
  };
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
  // Defensive: a test that forgets to call vi.useRealTimers() itself
  // (or fails before reaching it) would otherwise leak fake-timer state
  // into whichever test runs next in this file.
  vi.useRealTimers();
});

describe("useChatStream connection", () => {
  it("connects to the correct URL with the session id and token", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: "session-1", token: "jwt-token" }));

    expect(lastSocket().url).toContain("/api/v1/chat/session-1/stream");
    expect(lastSocket().url).toContain("token=jwt-token");
  });

  it("does not connect when sessionId is null", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: null, token: "jwt-token" }));

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("does not connect when disabled", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: "session-1", token: "jwt-token", enabled: false }));

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("transitions connectionStatus through connecting -> open", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    expect(result.current.connectionStatus).toBe("connecting");

    act(() => {
      lastSocket().emitOpen();
    });

    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));
  });

  it("closes the socket on unmount", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { unmount } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    const socket = lastSocket();

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("surfaces a readable error for the 4404 (session not found) close code", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitClose(4404);
    });

    await waitFor(() =>
      expect(result.current.error).toBe("Chat session not found, or it does not belong to you."),
    );
  });
});

describe("useChatStream reconnection (Section C, unit 9 audit finding)", () => {
  it("opens a new socket after an unexpected close, once the backoff delay elapses", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: "session-1", token: "jwt-token" }));
    const firstSocket = lastSocket();

    act(() => {
      firstSocket.emitClose(1006);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(lastSocket()).not.toBe(firstSocket);
    vi.useRealTimers();
  });

  it("a successful reconnect clears the error and reports connectionStatus 'open'", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitClose(1006);
    });
    expect(result.current.error).toContain("reconnecting (attempt 1/3)");

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      lastSocket().emitOpen();
    });

    expect(result.current.connectionStatus).toBe("open");
    vi.useRealTimers();
  });

  it("preserves the existing transcript across a reconnect of the SAME session (no server-side replay, unlike useAnalysisStream)", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
    });
    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-1"));
      lastSocket().emitMessage(tokenEvent("Hello"));
      lastSocket().emitMessage(doneEvent("assistant-msg-1"));
    });
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]?.content).toBe("Hello");

    act(() => {
      lastSocket().emitClose(1006);
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      lastSocket().emitOpen();
    });

    // The reconnect must not have wiped the transcript built up before
    // the drop -- there is no backend replay to deduplicate against, so
    // resetting messages here (as useAnalysisStream does for `events`)
    // would just silently lose everything said so far.
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]?.content).toBe("Hello");
    vi.useRealTimers();
  });

  it("marks an in-flight streaming reply as interrupted when the connection drops unexpectedly", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
    });
    act(() => {
      lastSocket().emitMessage(startEvent());
      lastSocket().emitMessage(tokenEvent("partial rep"));
    });
    expect(result.current.messages[0]?.isStreaming).toBe(true);

    act(() => {
      lastSocket().emitClose(1006);
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]?.isStreaming).toBe(false);
    expect(result.current.messages[0]?.isError).toBe(true);
    expect(result.current.messages[0]?.content).toBe("Connection lost before this reply finished.");
    vi.useRealTimers();
  });

  it("gives up after MAX_RECONNECT_ATTEMPTS and surfaces a terminal error", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      act(() => {
        lastSocket().emitClose(1006);
      });
      expect(result.current.error).toContain(`reconnecting (attempt ${attempt}/3)`);
      act(() => {
        vi.advanceTimersByTime(1000 * attempt);
      });
    }

    // The 4th close exhausts the budget -- no further socket is opened.
    const socketCountBeforeFinalClose = FakeWebSocket.instances.length;
    act(() => {
      lastSocket().emitClose(1006);
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(FakeWebSocket.instances).toHaveLength(socketCountBeforeFinalClose);
    expect(result.current.error).toBe(
      "Connection closed unexpectedly (code 1006) after 3 reconnect attempts.",
    );
    vi.useRealTimers();
  });

  it("does not reconnect on a normal close (code 1000)", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: "session-1", token: "jwt-token" }));
    act(() => {
      lastSocket().emitClose(1000);
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  it("does not reconnect on 4401 (unauthorized) or 4404 (not found) -- both are terminal", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatStream({ sessionId: "session-1", token: "jwt-token" }));
    act(() => {
      lastSocket().emitClose(4401);
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  it("clears any pending reconnect timer on unmount", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { unmount } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitClose(1006);
    });

    unmount();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    // No new socket was opened after unmount -- the pending setTimeout
    // was cleared, not left to fire against an unmounted hook.
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.useRealTimers();
  });
});

describe("useChatStream turn lifecycle", () => {
  it("builds an assistant message from start -> token -> token -> done", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent());
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "",
      isStreaming: true,
      isError: false,
    });
    expect(result.current.isAssistantTyping).toBe(true);

    act(() => {
      lastSocket().emitMessage(tokenEvent("Based "));
      lastSocket().emitMessage(tokenEvent("on the memo, "));
      lastSocket().emitMessage(tokenEvent("the verdict is BUY."));
    });
    await waitFor(() =>
      expect(result.current.messages[0]?.content).toBe("Based on the memo, the verdict is BUY."),
    );

    act(() => {
      lastSocket().emitMessage(doneEvent("msg-1"));
    });
    await waitFor(() => expect(result.current.messages[0]?.isStreaming).toBe(false));
    expect(result.current.isAssistantTyping).toBe(false);
  });

  it("ignores heartbeat events (no new message, no content change)", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent());
      lastSocket().emitMessage(tokenEvent("Hello"));
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    act(() => {
      lastSocket().emitMessage({
        session_id: "session-1",
        event_type: "heartbeat",
        token: "",
        message_id: null,
        is_final: false,
        error: null,
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]?.content).toBe("Hello");
  });

  it("marks the in-progress assistant message as errored on a mid-stream error event", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent());
      lastSocket().emitMessage(tokenEvent("Partial"));
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    act(() => {
      lastSocket().emitMessage(errorEvent("The AIRP Assistant timed out."));
    });

    await waitFor(() => expect(result.current.messages[0]?.isStreaming).toBe(false));
    expect(result.current.messages[0]).toMatchObject({
      isError: true,
      content: "The AIRP Assistant timed out.",
    });
    expect(result.current.isAssistantTyping).toBe(false);
  });

  it("renders a standalone error bubble for an error event with no prior start", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(errorEvent("'message' must be a non-empty string"));
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      isError: true,
      isStreaming: false,
      content: "'message' must be a non-empty string",
    });
  });

  it("the connection stays open after an error event -- another turn can still start", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(errorEvent("boom"));
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    act(() => {
      lastSocket().emitMessage(startEvent());
      lastSocket().emitMessage(tokenEvent("Second reply."));
      lastSocket().emitMessage(doneEvent("msg-2"));
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[1]).toMatchObject({
      content: "Second reply.",
      isStreaming: false,
      isError: false,
    });
    expect(lastSocket().closed).toBe(false);
  });
});

describe("useChatStream pendingAnalysisJobId (FEATURE 1)", () => {
  it("is null before any event arrives", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    expect(result.current.pendingAnalysisJobId).toBeNull();
  });

  it("is set the instant a 'start' event carries analysis_job_id", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent(null, "job-123"));
    });

    await waitFor(() => expect(result.current.pendingAnalysisJobId).toBe("job-123"));
  });

  it("stays null for a normal turn with no analysis_job_id", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent());
      lastSocket().emitMessage(tokenEvent("A P/E ratio of..."));
      lastSocket().emitMessage(doneEvent("msg-1"));
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.pendingAnalysisJobId).toBeNull();
  });

  it("clearPendingAnalysisJobId resets it back to null", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent(null, "job-123"));
    });
    await waitFor(() => expect(result.current.pendingAnalysisJobId).toBe("job-123"));

    act(() => {
      result.current.clearPendingAnalysisJobId();
    });

    expect(result.current.pendingAnalysisJobId).toBeNull();
  });
});

describe("useChatStream sendMessage", () => {
  it("appends an optimistic user message and sends {message} over the socket", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
    });
    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

    act(() => {
      result.current.sendMessage("What is the conviction score?");
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: "What is the conviction score?",
      isStreaming: false,
    });
    expect(lastSocket().sent).toEqual([
      JSON.stringify({ message: "What is the conviction score?" }),
    ]);
  });

  it("trims whitespace before sending and does nothing for a blank message", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
    });
    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

    act(() => {
      result.current.sendMessage("   ");
    });

    expect(result.current.messages).toHaveLength(0);
    expect(lastSocket().sent).toHaveLength(0);
  });

  it("does not send (or crash) when the socket is not open yet", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      result.current.sendMessage("too early");
    });

    expect(result.current.messages).toHaveLength(0);
    expect(lastSocket().sent).toHaveLength(0);
  });
});

describe("stale-socket race (B9)", () => {
  it("ignores a belated close from a superseded socket after a session switch", async () => {
    // Regression test for the exact root cause behind "Starting a new
    // conversation..." then "Connection closed unexpectedly (code
    // 1005)": this hook used to guard onopen/onmessage/onerror/onclose
    // with a single SHARED boolean ref, reset to true at the top of
    // every effect run -- the same bug useAnalysisStream.ts's own
    // "stale-socket race" test already covers for its sibling hook,
    // ported here after being missed when useChatStream was built.
    // Switching sessionId (a scope switch discarding the old session --
    // see useChatWidget.ts -- or React 18 StrictMode's double-invoke in
    // dev) tears down the first socket and opens a second; if the FIRST
    // socket's close event arrives asynchronously AFTER the second has
    // already taken over, it must not be allowed to overwrite the
    // second (real, current) socket's state.
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => useChatStream({ sessionId, token: "jwt-token" }),
      { initialProps: { sessionId: "session-1" } },
    );

    const staleSocket = lastSocket();

    rerender({ sessionId: "session-2" });
    const currentSocket = lastSocket();
    expect(currentSocket).not.toBe(staleSocket);

    act(() => {
      currentSocket.emitOpen();
    });
    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

    // The stale socket's close event arrives late, after the real
    // connection is already open -- it must be ignored entirely.
    act(() => {
      staleSocket.emitClose(1005);
    });

    expect(result.current.connectionStatus).toBe("open");
    expect(result.current.error).toBeNull();
  });

  it("does not let a stale socket's belated 'start' event corrupt the new session's transcript", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => useChatStream({ sessionId, token: "jwt-token" }),
      { initialProps: { sessionId: "session-1" } },
    );
    const staleSocket = lastSocket();

    rerender({ sessionId: "session-2" });
    const currentSocket = lastSocket();

    act(() => {
      currentSocket.emitOpen();
    });
    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

    act(() => {
      staleSocket.emitMessage(startEvent());
    });

    expect(result.current.messages).toHaveLength(0);
  });
});

describe("useChatStream serverId confirmation (B9)", () => {
  it("fills in the user message's serverId from the 'start' event's message_id", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
    });
    await waitFor(() => expect(result.current.connectionStatus).toBe("open"));

    act(() => {
      result.current.sendMessage("What is the conviction score?");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]?.serverId).toBeNull();

    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-1"));
    });

    await waitFor(() => expect(result.current.messages[0]?.serverId).toBe("user-msg-1"));
  });

  it("fills in the assistant message's serverId from the 'done' event's message_id", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent("user-msg-1"));
      lastSocket().emitMessage(tokenEvent("BUY."));
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]?.serverId).toBeNull();

    act(() => {
      lastSocket().emitMessage(doneEvent("assistant-msg-1"));
    });

    await waitFor(() => expect(result.current.messages[0]?.serverId).toBe("assistant-msg-1"));
  });

  it("a second turn's 'start' does not disturb an already-confirmed prior user message", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );

    act(() => {
      lastSocket().emitOpen();
      result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-1"));
      lastSocket().emitMessage(doneEvent("assistant-msg-1"));
    });
    await waitFor(() => expect(result.current.messages[0]?.serverId).toBe("user-msg-1"));

    act(() => {
      result.current.sendMessage("second");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(3));
    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-2"));
    });

    await waitFor(() => expect(result.current.messages[2]?.serverId).toBe("user-msg-2"));
    // First turn's ids are untouched by the second turn's confirmation.
    expect(result.current.messages[0]?.serverId).toBe("user-msg-1");
    expect(result.current.messages[1]?.serverId).toBe("assistant-msg-1");
  });
});

describe("useChatStream editMessage (B9)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function setUpConfirmedUserMessage() {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
      result.current.sendMessage("What was the verdict on TCS?");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-1"));
      lastSocket().emitMessage(tokenEvent("BUY."));
      lastSocket().emitMessage(doneEvent("assistant-msg-1"));
    });
    await waitFor(() => expect(result.current.messages[0]?.serverId).toBe("user-msg-1"));
    return { result };
  }

  it("returns false and sets editError when the message has no confirmed serverId yet", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
      result.current.sendMessage("unconfirmed");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.editMessage(result.current.messages[0]!.id, "edited");
    });

    expect(outcome).toBe(false);
    expect(result.current.editError).not.toBeNull();
  });

  it("returns false for an assistant message (only user turns are editable)", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
      lastSocket().emitMessage(startEvent("user-msg-1"));
      lastSocket().emitMessage(doneEvent("assistant-msg-1"));
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.editMessage(result.current.messages[0]!.id, "edited");
    });

    expect(outcome).toBe(false);
  });

  it("deletes-and-resends on a valid edit: truncates the message and everything after it, then sends the new text", async () => {
    const { result } = await setUpConfirmedUserMessage();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { deleted_count: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.editMessage(
        result.current.messages[0]!.id,
        "What was the verdict on Infosys?",
      );
    });

    expect(outcome).toBe(true);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/chat/sessions/session-1/messages/user-msg-1");
    expect(options.method).toBe("DELETE");

    // The stale user+assistant pair is gone, replaced by the freshly
    // sent edited user message (the socket has no reply yet).
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: "What was the verdict on Infosys?",
    });
    expect(lastSocket().sent.at(-1)).toBe(
      JSON.stringify({ message: "What was the verdict on Infosys?" }),
    );
  });

  it("surfaces a failed delete as editError and does not touch the transcript or the socket", async () => {
    const { result } = await setUpConfirmedUserMessage();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "No message found for message_id" }));
    vi.stubGlobal("fetch", fetchMock);

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.editMessage(result.current.messages[0]!.id, "edited");
    });

    expect(outcome).toBe(false);
    expect(result.current.editError).toBe("No message found for message_id");
    expect(result.current.messages).toHaveLength(2);
    expect(lastSocket().sent).toHaveLength(1);
  });

  it("refuses to edit while the assistant is still typing", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() =>
      useChatStream({ sessionId: "session-1", token: "jwt-token" }),
    );
    act(() => {
      lastSocket().emitOpen();
      result.current.sendMessage("first");
    });
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    act(() => {
      lastSocket().emitMessage(startEvent("user-msg-1"));
    });
    await waitFor(() => expect(result.current.isAssistantTyping).toBe(true));

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.editMessage(result.current.messages[0]!.id, "edited");
    });

    expect(outcome).toBe(false);
    expect(result.current.editError).not.toBeNull();
  });
});
