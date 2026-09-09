// frontend/src/test/ChatWidget.test.tsx
// Tests for ChatWidget (T-105). Renders the component directly (not
// via RootLayout -- RootLayout.test.tsx covers the "only mounted when
// authenticated" gate) wrapped in AuthContext + MemoryRouter, and
// stubs global.fetch (session creation, T-103) + global.WebSocket
// (the fake class test/useChatStream.test.ts already established, T-104)
// so the whole open -> create session -> stream a reply flow runs
// fully offline.

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatWidget } from "@/components/chat/ChatWidget";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";

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
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
  }

  emitOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  emitMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
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

const AUTHENTICATED: AuthContextValue = {
  user: {
    id: "1",
    email: "a@example.com",
    display_name: null,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  accessToken: "jwt-token",
  isAuthenticated: true,
  register: async () => {},
  login: async () => {},
  logout: async () => {},
};

function renderWidget(initialPath = "/dashboard"): void {
  render(
    <AuthContext.Provider value={AUTHENTICATED}>
      <MemoryRouter initialEntries={[initialPath]}>
        <ChatWidget />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

function sessionResponse(overrides: Record<string, unknown> = {}): unknown {
  return {
    id: "session-1",
    session_type: "portfolio_wide",
    analysis_id: null,
    title: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
});

describe("ChatWidget collapsed state", () => {
  it("renders only the floating toggle button before it is opened", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderWidget();

    expect(screen.getByRole("button", { name: "Open AIRP Assistant chat" })).toBeInTheDocument();
    expect(screen.queryByTestId("chat-widget-panel")).not.toBeInTheDocument();
  });
});

describe("ChatWidget opening", () => {
  it("opens the panel and shows the portfolio-wide scope label on the dashboard", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, sessionResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget("/dashboard");

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));

    expect(screen.getByTestId("chat-widget-panel")).toBeInTheDocument();
    expect(screen.getByText("Asking about your portfolio")).toBeInTheDocument();
  });

  it("shows the memo-scoped label and empty-state copy when opened from a memo", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(201, sessionResponse({ session_type: "memo_scoped", analysis_id: "job-42" })),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget("/analysis/job-42/memo");

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));

    expect(screen.getByText("Asking about this memo")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Ask a question about this Investment Memo/i)).toBeInTheDocument(),
    );

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.analysis_id).toBe("job-42");
  });

  it("closes the panel via the minimize button, keeping the floating toggle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, sessionResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    expect(screen.getByTestId("chat-widget-panel")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Minimize AIRP Assistant chat" }));

    expect(screen.queryByTestId("chat-widget-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open AIRP Assistant chat" })).toBeInTheDocument();
  });
});

describe("ChatWidget conversation", () => {
  it("sends a message and streams the assistant's reply into the transcript", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, sessionResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    const socket = lastSocket();
    act(() => {
      socket.emitOpen();
    });

    const composer = screen.getByLabelText("Message the AIRP Assistant");
    await user.type(composer, "What is the conviction score?");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(screen.getByText("What is the conviction score?")).toBeInTheDocument();
    expect(socket.sent).toEqual([JSON.stringify({ message: "What is the conviction score?" })]);

    act(() => {
      socket.emitMessage({
        session_id: "session-1",
        event_type: "start",
        token: "",
        message_id: null,
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "token",
        token: "Conviction is 8/10.",
        message_id: null,
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "done",
        token: "",
        message_id: "msg-1",
        is_final: true,
        error: null,
      });
    });

    await waitFor(() => expect(screen.getByText("Conviction is 8/10.")).toBeInTheDocument());
  });

  it("disables the composer while the session is being created, then enables it", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const fetchMock = vi.fn().mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));

    expect(screen.getByLabelText("Message the AIRP Assistant")).toBeDisabled();

    await act(async () => {
      resolveFetch(jsonResponse(201, sessionResponse()));
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(screen.getByLabelText("Message the AIRP Assistant")).not.toBeDisabled(),
    );
  });

  it("shows the session error when the backend rejects session creation", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "analysis_id=job-42 is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget("/analysis/job-42/memo");

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));

    await waitFor(() =>
      expect(screen.getByText("analysis_id=job-42 is not ready yet")).toBeInTheDocument(),
    );
  });
});

describe("ChatWidget edit-and-resend (B9)", () => {
  function routedFetchMock(deleteResponse: unknown = { deleted_count: 2 }) {
    return vi.fn((_url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "DELETE") {
        return Promise.resolve(jsonResponse(200, deleteResponse));
      }
      return Promise.resolve(jsonResponse(201, sessionResponse()));
    });
  }

  it("shows an edit affordance on a confirmed user message and lets the person edit it", async () => {
    const fetchMock = routedFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = lastSocket();
    act(() => {
      socket.emitOpen();
    });

    const composer = screen.getByLabelText("Message the AIRP Assistant");
    await user.type(composer, "What was the verdict on TCS?");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    act(() => {
      socket.emitMessage({
        session_id: "session-1",
        event_type: "start",
        token: "",
        message_id: "user-msg-1",
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "token",
        token: "BUY.",
        message_id: null,
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "done",
        token: "",
        message_id: "assistant-msg-1",
        is_final: true,
        error: null,
      });
    });
    await waitFor(() => expect(screen.getByText("BUY.")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Edit message" }));
    const editBox = screen.getByLabelText("Edit message");
    expect(editBox).toHaveValue("What was the verdict on TCS?");

    await user.clear(editBox);
    await user.type(editBox, "What was the verdict on Infosys?");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const deleteCall = fetchMock.mock.calls.find((call) => call[1]?.method === "DELETE");
    expect(deleteCall?.[0]).toContain("/chat/sessions/session-1/messages/user-msg-1");

    await waitFor(() =>
      expect(screen.getByText("What was the verdict on Infosys?")).toBeInTheDocument(),
    );
    expect(screen.queryByText("What was the verdict on TCS?")).not.toBeInTheDocument();
    expect(screen.queryByText("BUY.")).not.toBeInTheDocument();
    expect(socket.sent.at(-1)).toBe(
      JSON.stringify({ message: "What was the verdict on Infosys?" }),
    );
  });

  it("Cancel leaves the original message unchanged", async () => {
    const fetchMock = routedFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = lastSocket();
    act(() => {
      socket.emitOpen();
    });

    const composer = screen.getByLabelText("Message the AIRP Assistant");
    await user.type(composer, "Original question");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    act(() => {
      socket.emitMessage({
        session_id: "session-1",
        event_type: "start",
        token: "",
        message_id: "user-msg-1",
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "done",
        token: "",
        message_id: "assistant-msg-1",
        is_final: true,
        error: null,
      });
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit message" })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Edit message" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Original question")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);
  });

  it("does not show an edit affordance on assistant messages", async () => {
    const fetchMock = routedFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = lastSocket();
    act(() => {
      socket.emitOpen();
    });

    const composer = screen.getByLabelText("Message the AIRP Assistant");
    await user.type(composer, "hello");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    act(() => {
      socket.emitMessage({
        session_id: "session-1",
        event_type: "start",
        token: "",
        message_id: "user-msg-1",
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "token",
        token: "hi there",
        message_id: null,
        is_final: false,
        error: null,
      });
      socket.emitMessage({
        session_id: "session-1",
        event_type: "done",
        token: "",
        message_id: "assistant-msg-1",
        is_final: true,
        error: null,
      });
    });
    await waitFor(() => expect(screen.getByText("hi there")).toBeInTheDocument());

    // Exactly one edit affordance -- the user's own turn, not the
    // assistant's reply.
    expect(screen.getAllByRole("button", { name: "Edit message" })).toHaveLength(1);
  });
});

describe("ChatWidget history panel (B9)", () => {
  function messagesResponse(sessionId: string): unknown {
    return {
      session_id: sessionId,
      items: [
        {
          id: "msg-1",
          session_id: sessionId,
          role: "user",
          content: "What was the verdict on TCS?",
          tool_calls: null,
          tool_name: null,
          tokens_used: null,
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "msg-2",
          session_id: sessionId,
          role: "assistant",
          content: "AIRP rated TCS a BUY.",
          tool_calls: null,
          tool_name: null,
          tokens_used: null,
          created_at: "2026-01-01T00:00:01Z",
        },
      ],
      total_count: 2,
      limit: 200,
      offset: 0,
      has_more: false,
    };
  }

  function routedFetchMock() {
    return vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && url.includes("/chat/sessions")) {
        return jsonResponse(201, sessionResponse());
      }
      if (url.includes("/messages")) {
        return jsonResponse(200, messagesResponse("session-a"));
      }
      return jsonResponse(200, {
        items: [sessionResponse({ id: "session-a", title: "About TCS" })],
        total_count: 1,
        limit: 20,
        offset: 0,
        has_more: false,
      });
    });
  }

  it("opens the history panel and lists past conversations", async () => {
    vi.stubGlobal("fetch", routedFetchMock());
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await user.click(screen.getByRole("button", { name: "View past conversations" }));

    expect(screen.getByTestId("chat-history-panel")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("About TCS")).toBeInTheDocument());
  });

  it("resumes a past conversation's transcript when a history entry is clicked", async () => {
    vi.stubGlobal("fetch", routedFetchMock());
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await user.click(screen.getByRole("button", { name: "View past conversations" }));
    await waitFor(() => expect(screen.getByText("About TCS")).toBeInTheDocument());

    await user.click(screen.getByText("About TCS"));

    // Back to the live transcript view, now showing the resumed turns.
    await waitFor(() => expect(screen.queryByTestId("chat-history-panel")).not.toBeInTheDocument());
    expect(screen.getByText("What was the verdict on TCS?")).toBeInTheDocument();
    expect(screen.getByText("AIRP rated TCS a BUY.")).toBeInTheDocument();
  });

  it("starting a new conversation returns to the live transcript with no resumed messages", async () => {
    vi.stubGlobal("fetch", routedFetchMock());
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const user = userEvent.setup();
    renderWidget();

    await user.click(screen.getByRole("button", { name: "Open AIRP Assistant chat" }));
    await user.click(screen.getByRole("button", { name: "View past conversations" }));
    await waitFor(() => expect(screen.getByText("About TCS")).toBeInTheDocument());
    await user.click(screen.getByText("About TCS"));
    await waitFor(() =>
      expect(screen.getByText("What was the verdict on TCS?")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Start a new conversation" }));

    await waitFor(() =>
      expect(screen.queryByText("What was the verdict on TCS?")).not.toBeInTheDocument(),
    );
  });
});
