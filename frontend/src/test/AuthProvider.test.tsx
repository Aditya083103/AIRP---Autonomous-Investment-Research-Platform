// frontend/src/test/AuthProvider.test.tsx
// Tests for AuthProvider + useAuth (T-056), exercised through a small
// probe component rather than testing the hook in isolation -- hooks
// only run inside a component, and this mirrors how every real
// consumer (LoginPage, RegisterPage, DashboardPage) actually uses it.
// global.fetch is mocked per test; no real network call is made.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/hooks/useAuth";
import { AuthProvider } from "@/providers/AuthProvider";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const TOKEN_RESPONSE = {
  access_token: "fake-jwt-token",
  token_type: "bearer",
  expires_in_minutes: 60,
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    email: "a@example.com",
    display_name: "Aditya",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
};

function AuthProbe(): JSX.Element {
  const { user, accessToken, isAuthenticated, login, register, logout } = useAuth();
  return (
    <div>
      <p data-testid="status">{isAuthenticated ? "authenticated" : "anonymous"}</p>
      <p data-testid="email">{user?.email ?? "none"}</p>
      <p data-testid="token">{accessToken ?? "none"}</p>
      <button onClick={() => void login({ email: "a@example.com", password: "password123" })}>
        Login
      </button>
      <button onClick={() => void register({ email: "a@example.com", password: "password123" })}>
        Register
      </button>
      <button onClick={() => void logout()}>Logout</button>
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthProvider", () => {
  it("starts unauthenticated", () => {
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
  });

  it("becomes authenticated after a successful login", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, TOKEN_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("email")).toHaveTextContent("a@example.com");
    expect(screen.getByTestId("token")).toHaveTextContent("fake-jwt-token");
  });

  it("becomes authenticated after a successful register", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, TOKEN_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
  });

  it("sends credentials: include so the httpOnly cookie round-trips", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, TOKEN_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.credentials).toBe("include");
  });

  it("clears state on logout even though it also calls the API", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, TOKEN_RESPONSE))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Login" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });
});
