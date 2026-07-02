// frontend/src/test/LoginPage.test.tsx
// Tests for LoginPage (T-056). Wraps a fake AuthContext value (rather
// than the real AuthProvider + a mocked fetch) so these tests focus on
// the page's own behaviour -- validation, error display, and the
// redirect -- independent of AuthProvider's own tests (AuthProvider.test.tsx).

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AuthApiError } from "@/api/auth";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { LoginPage } from "@/pages/LoginPage";

function renderLoginPage(login: AuthContextValue["login"]): void {
  const value: AuthContextValue = {
    user: null,
    accessToken: null,
    isAuthenticated: false,
    register: async () => {},
    login,
    logout: async () => {},
  };

  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<p>Dashboard page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("LoginPage", () => {
  it("shows validation errors when submitted empty", async () => {
    const user = userEvent.setup();
    renderLoginPage(vi.fn());

    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText("Email is required.")).toBeInTheDocument();
    expect(await screen.findByText("Password is required.")).toBeInTheDocument();
  });

  it("shows the backend's error message on failed login", async () => {
    const login = vi.fn().mockRejectedValue(new AuthApiError(401, "Incorrect email or password"));
    const user = userEvent.setup();
    renderLoginPage(login);

    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText("Incorrect email or password")).toBeInTheDocument();
  });

  it("redirects to /dashboard after a successful login", async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderLoginPage(login);

    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
  });
});
