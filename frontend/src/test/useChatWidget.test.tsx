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
    await waitFor(() => expect(result.current.session).toBeNull());

    // The widget is still open, so the new scope's session is created
    // automatically -- no second toggle() needed.
    await waitFor(() => expect(result.current.session?.analysis_id).toBe("job-2"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
