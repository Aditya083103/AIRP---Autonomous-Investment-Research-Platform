// frontend/src/test/DashboardPage.test.tsx
// Tests for DashboardPage (T-056 placeholder): greets the logged-in user
// by display name (falling back to email), and the logout button calls
// through to useAuth().logout().

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { DashboardPage } from "@/pages/DashboardPage";

function renderDashboard(overrides: Partial<AuthContextValue> = {}): void {
  const value: AuthContextValue = {
    user: {
      id: "1",
      email: "a@example.com",
      display_name: "Aditya",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    },
    accessToken: "token",
    isAuthenticated: true,
    register: async () => {},
    login: async () => {},
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };

  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("DashboardPage", () => {
  it("greets the user by display name", () => {
    renderDashboard();
    expect(screen.getByRole("heading", { name: /welcome, aditya/i })).toBeInTheDocument();
  });

  it("falls back to email when there is no display name", () => {
    renderDashboard({
      user: {
        id: "1",
        email: "a@example.com",
        display_name: null,
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
      },
    });
    expect(screen.getByRole("heading", { name: /welcome, a@example.com/i })).toBeInTheDocument();
  });

  it("calls logout when the log out button is clicked", async () => {
    const user = userEvent.setup();
    const logoutMock = vi.fn().mockResolvedValue(undefined);
    renderDashboard({ logout: logoutMock });

    await user.click(screen.getByRole("button", { name: /log out/i }));

    expect(logoutMock).toHaveBeenCalledTimes(1);
  });
});
