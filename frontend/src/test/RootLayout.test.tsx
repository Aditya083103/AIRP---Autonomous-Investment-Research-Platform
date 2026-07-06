// frontend/src/test/RootLayout.test.tsx
// Tests for RootLayout's header. T-056's original tests (shows "Log
// in" / "Get started" when signed out, and the user's email + a "Log
// out" button when signed in) are unchanged below. T-065 adds the
// hamburger nav tests: the mobile panel is closed by default (so it
// never overlaps with the always-rendered desktop nav bar and produces
// a duplicate-link false positive), opens on toggle-button click,
// contains the three primary links, and closes again after a link
// inside it is clicked or the toggle is clicked a second time.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("RootLayout primary navigation", () => {
  it("renders the three primary links once in the always-visible desktop bar", () => {
    renderLayout(false);

    expect(screen.getByRole("link", { name: "New analysis" })).toHaveAttribute("href", "/analysis");
    expect(screen.getByRole("link", { name: "Compare" })).toHaveAttribute("href", "/compare");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard");
  });
});

describe("RootLayout mobile nav panel", () => {
  it("does not render the mobile panel before the toggle is clicked", () => {
    renderLayout(false);

    expect(screen.queryByTestId("mobile-nav-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens the panel with all links and flips the toggle button's label/state", async () => {
    const user = userEvent.setup();
    renderLayout(false);

    await user.click(screen.getByRole("button", { name: "Open menu" }));

    const panel = screen.getByTestId("mobile-nav-panel");
    const scoped = within(panel);
    expect(scoped.getByRole("link", { name: "New analysis" })).toBeInTheDocument();
    expect(scoped.getByRole("link", { name: "Compare" })).toBeInTheDocument();
    expect(scoped.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Close menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("closes the panel when the toggle is clicked a second time", async () => {
    const user = userEvent.setup();
    renderLayout(false);

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    await user.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.queryByTestId("mobile-nav-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open menu" })).toBeInTheDocument();
  });

  it("closes the panel after a link inside it is clicked", async () => {
    const user = userEvent.setup();
    renderLayout(false);

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const panel = screen.getByTestId("mobile-nav-panel");
    await user.click(within(panel).getByRole("link", { name: "Compare" }));

    expect(screen.queryByTestId("mobile-nav-panel")).not.toBeInTheDocument();
  });
});
