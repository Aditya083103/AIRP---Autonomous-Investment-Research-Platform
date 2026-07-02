// frontend/src/test/RootLayout.test.tsx
// Tests for RootLayout's header (T-056): shows "Log in" / "Get started"
// when signed out, and the user's email + a "Log out" button when
// signed in. The rest of RootLayout (brand link, footer, <Outlet />
// wiring) was established in T-053 and is unchanged here.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RootLayout } from "@/components/layout/RootLayout";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";

function renderLayout(isAuthenticated: boolean): void {
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
      <MemoryRouter>
        <RootLayout />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("RootLayout header", () => {
  it("shows Log in and Get started when signed out", () => {
    renderLayout(false);
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/register");
  });

  it("shows the user's email and a Log out button when signed in", () => {
    renderLayout(true);
    expect(screen.getByText("a@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Log in" })).not.toBeInTheDocument();
  });
});
