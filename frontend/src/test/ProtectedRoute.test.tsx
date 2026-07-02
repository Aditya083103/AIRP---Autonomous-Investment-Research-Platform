// frontend/src/test/ProtectedRoute.test.tsx
// Tests for ProtectedRoute (T-056). Renders a tiny two-route MemoryRouter
// (the protected route and /login) rather than mocking useAuth directly,
// so the test exercises the real <Navigate> redirect behaviour.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";

function renderWithAuth(isAuthenticated: boolean): void {
  const value: AuthContextValue = {
    user: isAuthenticated
      ? {
          id: "1",
          email: "a@example.com",
          display_name: null,
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
        }
      : null,
    accessToken: isAuthenticated ? "token" : null,
    isAuthenticated,
    register: async () => {},
    login: async () => {},
    logout: async () => {},
  };

  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={["/dashboard"]}>
        <Routes>
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <p>Protected content</p>
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<p>Login page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("ProtectedRoute", () => {
  it("renders the protected content when authenticated", () => {
    renderWithAuth(true);
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("redirects to /login when not authenticated", () => {
    renderWithAuth(false);
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });
});
