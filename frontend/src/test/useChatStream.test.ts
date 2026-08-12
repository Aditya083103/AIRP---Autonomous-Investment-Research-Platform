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

function startEvent(): unknown {
  return {
    session_id: "session-1",
    event_type: "start",
    token: "",
    message_id: null,
    is_final: false,
    error: null,
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
