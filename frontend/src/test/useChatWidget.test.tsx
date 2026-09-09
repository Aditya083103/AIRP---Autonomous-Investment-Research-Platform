// frontend/src/test/useChatWidget.test.tsx
// Tests for useChatWidget (T-105). Follows this codebase's established
// convention (test/DashboardPage.test.tsx, test/analysisApi.test.ts,
// ...) of stubbing global.fetch and global.WebSocket directly rather
// than mocking src/api/chat.ts or src/hooks/useChatStream.ts as
// modules -- no test file in this repo uses vi.mock() for an internal
// module, and this file does not introduce a new pattern.
//
// A tiny NavigationHelper component (rendered inside the same
// MemoryRouter as the hook under test) exposes react-router's
// useNavigate() onto `window.__testNavigate` for the one test that
// needs to simulate an in-app route change (moving from one memo to
// another) without remounting the hook -- MemoryRouter's own
// `initialEntries` only sets the STARTING route, so a real navigate()
// call is the only way to change location.pathname for an
// already-mounted hook the way RootLayout's real <ChatWidget /> would
// experience it when the person clicks from one memo to another.

import { act, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode, useEffect } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { useChatWidget } from "@/hooks/useChatWidget";

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

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(): void {}

  close(): void {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
  }
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

const SIGNED_OUT: AuthContextValue = {
  user: null,
  accessToken: null,
  isAuthenticated: false,
  register: async () => {},
  login: async () => {},
  logout: async () => {},
};

function NavigationHelper(): null {
  const navigate = useNavigate();
  useEffect(() => {
    (window as unknown as { __testNavigate: typeof navigate }).__testNavigate = navigate;
  }, [navigate]);
  return null;
}

function createWrapper(initialPath: string, authValue: AuthContextValue) {
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return (
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={[initialPath]}>
          <NavigationHelper />
          {children}
        </MemoryRouter>
      </AuthContext.Provider>
    );
  };
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
  delete (window as unknown as { __testNavigate?: unknown }).__testNavigate;
});

describe("useChatWidget scope derivation", () => {
  it("derives portfolio_wide on the dashboard", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    expect(result.current.scope).toEqual({ sessionType: "portfolio_wide", analysisId: null });
  });

  it("derives memo_scoped with the jobId on a memo route", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/analysis/job-42/memo", AUTHENTICATED),
    });

    expect(result.current.scope).toEqual({ sessionType: "memo_scoped", analysisId: "job-42" });
  });
});

describe("useChatWidget open/close", () => {
  it("starts closed and toggle() opens it", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    expect(result.current.isOpen).toBe(false);

    act(() => {
      result.current.toggle();
    });

    expect(result.current.isOpen).toBe(true);
  });

  it("close() closes an open widget", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
    });
    expect(result.current.isOpen).toBe(true);

    act(() => {
      result.current.close();
    });
    expect(result.current.isOpen).toBe(false);
  });

  it("does not create a session before the widget is opened", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatWidget(), { wrapper: createWrapper("/dashboard", AUTHENTICATED) });

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("useChatWidget session creation", () => {
  it("creates a portfolio_wide session with no analysis_id when opened from the dashboard", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, sessionResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
    });

    await waitFor(() => expect(result.current.session).not.toBeNull());
    expect(result.current.session?.session_type).toBe("portfolio_wide");

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.session_type).toBe("portfolio_wide");
    expect(body).not.toHaveProperty("analysis_id");
  });

  it("creates a memo_scoped session with the route's analysis_id when opened from a memo", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(201, sessionResponse({ session_type: "memo_scoped", analysis_id: "job-42" })),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/analysis/job-42/memo", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
    });

    await waitFor(() => expect(result.current.session).not.toBeNull());
    expect(result.current.session?.session_type).toBe("memo_scoped");
    expect(result.current.session?.analysis_id).toBe("job-42");

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.analysis_id).toBe("job-42");
  });

  it("does not create a session when signed out", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", SIGNED_OUT),
    });

    act(() => {
      result.current.toggle();
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces a 409 (analysis not ready) as sessionError", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "analysis_id=job-42 is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/analysis/job-42/memo", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
    });

    await waitFor(() =>
      expect(result.current.sessionError).toBe("analysis_id=job-42 is not ready yet"),
    );
    expect(result.current.session).toBeNull();
  });

  it("does not re-create a session on a second toggle-close-open cycle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, sessionResponse()));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle(); // open
    });
    await waitFor(() => expect(result.current.session).not.toBeNull());

    act(() => {
      result.current.toggle(); // close
    });
    act(() => {
      result.current.toggle(); // re-open, same scope
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("useChatWidget scope changes", () => {
  it("discards the session when navigating from one memo to a different one", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(201, sessionResponse({ session_type: "memo_scoped", analysis_id: "job-1" })),
      )
      .mockResolvedValueOnce(
        jsonResponse(201, sessionResponse({ session_type: "memo_scoped", analysis_id: "job-2" })),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/analysis/job-1/memo", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
    });
    await waitFor(() => expect(result.current.session?.analysis_id).toBe("job-1"));

    act(() => {
      (window as unknown as { __testNavigate: (path: string) => void }).__testNavigate(
        "/analysis/job-2/memo",
      );
    });

    await waitFor(() => expect(result.current.scope.analysisId).toBe("job-2"));

    // Not asserted here: an intermediate `session === null` state.
    // The existing scope-change reset effect (see useChatWidget.ts,
    // keyed on chatScopeKey) does clear session synchronously the
    // moment scopeKey changes, and the new scope's session is then
    // created automatically -- but with a mocked fetch that resolves
    // with no real delay, that whole discard-then-recreate sequence
    // completes via microtasks alone, faster than waitFor's next poll.
    // The null state is real but exists for a fraction of a
    // millisecond; asserting it here is inherently racy, not a
    // meaningful behavioural guarantee -- what actually matters to a
    // person using the widget is that the FINAL session is scoped to
    // the new memo, never left stuck on the old one, which the two
    // checks below already prove: the ending session belongs to
    // job-2 (not job-1), and it was independently fetched (not the
    // old session object merely relabelled).

    // The widget is still open, so the new scope's session is created
    // automatically -- no second toggle() needed.
    await waitFor(() => expect(result.current.session?.analysis_id).toBe("job-2"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

// (B9) Conversation list -- revisit and continue a past session. See
// useChatWidget.ts's own "Conversation list state" section: listing
// sessions (GET /chat/sessions), resuming one (GET .../messages), and
// discarding a resumed session back to normal scope-based creation.

function messagesResponse(sessionId: string, overrides: Record<string, unknown> = {}): unknown {
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
    ...overrides,
  };
}

/** Routes a single global fetch mock to the right canned response by URL/method, mirroring how the real backend's three chat endpoints differ -- avoids one giant if/else duplicated across every test below. */
function routedFetchMock(options: {
  listResponse?: unknown;
  messagesResponses?: Record<string, unknown>;
  createResponse?: unknown;
}) {
  return vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "POST" && url.includes("/chat/sessions")) {
      return jsonResponse(201, options.createResponse ?? sessionResponse());
    }
    if (url.includes("/messages")) {
      const match = /\/chat\/sessions\/([^/?]+)\/messages/.exec(url);
      const sessionId = match?.[1] ?? "session-1";
      const body = options.messagesResponses?.[sessionId] ?? messagesResponse(sessionId);
      return jsonResponse(200, body);
    }
    return jsonResponse(
      200,
      options.listResponse ?? { items: [], total_count: 0, limit: 20, offset: 0, has_more: false },
    );
  });
}

describe("useChatWidget conversation history (B9)", () => {
  it("does not fetch the session list before the history panel is opened", () => {
    const fetchMock = routedFetchMock({});
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useChatWidget(), { wrapper: createWrapper("/dashboard", AUTHENTICATED) });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("toggleHistory() loads and exposes the caller's past sessions", async () => {
    const listResponse = {
      items: [
        sessionResponse({ id: "session-a", title: "About TCS" }),
        sessionResponse({ id: "session-b", title: null }),
      ],
      total_count: 2,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    const fetchMock = routedFetchMock({ listResponse });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    expect(result.current.isHistoryOpen).toBe(false);

    act(() => {
      result.current.toggleHistory();
    });

    expect(result.current.isHistoryOpen).toBe(true);
    await waitFor(() => expect(result.current.historySessions).toHaveLength(2));
    expect(result.current.historySessions.map((s) => s.id)).toEqual(["session-a", "session-b"]);
  });

  it("openHistorySession() resumes a past session's transcript and closes the history panel", async () => {
    const listResponse = {
      items: [sessionResponse({ id: "session-a", title: "About TCS" })],
      total_count: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    const fetchMock = routedFetchMock({
      listResponse,
      messagesResponses: { "session-a": messagesResponse("session-a") },
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle(); // open widget
      result.current.toggleHistory();
    });
    await waitFor(() => expect(result.current.historySessions).toHaveLength(1));

    act(() => {
      result.current.openHistorySession("session-a");
    });

    await waitFor(() => expect(result.current.session?.id).toBe("session-a"));
    expect(result.current.isHistoryOpen).toBe(false);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: "What was the verdict on TCS?",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "AIRP rated TCS a BUY.",
    });
  });

  it("openHistorySession() surfaces a fetch failure as sessionError without changing the active session", async () => {
    const listResponse = {
      items: [sessionResponse({ id: "session-a" })],
      total_count: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST") return jsonResponse(201, sessionResponse());
      if (url.includes("/messages")) {
        return jsonResponse(404, { detail: "No chat session found for the given session_id" });
      }
      return jsonResponse(200, listResponse);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggleHistory();
    });
    await waitFor(() => expect(result.current.historySessions).toHaveLength(1));

    act(() => {
      result.current.openHistorySession("session-a");
    });

    await waitFor(() =>
      expect(result.current.sessionError).toBe("No chat session found for the given session_id"),
    );
    expect(result.current.session).toBeNull();
  });

  it("startNewConversation() discards a resumed session and lets the current scope auto-create a fresh one", async () => {
    const listResponse = {
      items: [sessionResponse({ id: "session-a" })],
      total_count: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    const fetchMock = routedFetchMock({
      listResponse,
      messagesResponses: { "session-a": messagesResponse("session-a") },
      createResponse: sessionResponse({ id: "session-fresh" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const { result } = renderHook(() => useChatWidget(), {
      wrapper: createWrapper("/dashboard", AUTHENTICATED),
    });

    act(() => {
      result.current.toggle();
      result.current.toggleHistory();
    });
    await waitFor(() => expect(result.current.historySessions).toHaveLength(1));

    act(() => {
      result.current.openHistorySession("session-a");
    });
    await waitFor(() => expect(result.current.session?.id).toBe("session-a"));
    expect(result.current.messages).toHaveLength(2);

    act(() => {
      result.current.startNewConversation();
    });

    await waitFor(() => expect(result.current.session?.id).toBe("session-fresh"));
    expect(result.current.messages).toHaveLength(0);
  });
});
