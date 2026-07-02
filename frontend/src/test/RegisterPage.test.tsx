// frontend/src/test/RegisterPage.test.tsx
// Tests for RegisterPage (T-056), same fake-AuthContext approach as
// LoginPage.test.tsx.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AuthApiError } from "@/api/auth";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { RegisterPage } from "@/pages/RegisterPage";

function renderRegisterPage(register: AuthContextValue["register"]): void {
  const value: AuthContextValue = {
    user: null,
    accessToken: null,
    isAuthenticated: false,
    register,
    login: async () => {},
    logout: async () => {},
  };

  render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/dashboard" element={<p>Dashboard page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("RegisterPage", () => {
  it("shows an error when the passwords do not match", async () => {
    const user = userEvent.setup();
    renderRegisterPage(vi.fn());

    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm password"), "different-password");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
  });

  it("shows the backend's error message on a duplicate email", async () => {
    const register = vi
      .fn()
      .mockRejectedValue(new AuthApiError(409, "A user with this email already exists"));
    const user = userEvent.setup();
    renderRegisterPage(register);

    await user.type(screen.getByLabelText("Email"), "dup@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("A user with this email already exists")).toBeInTheDocument();
  });

  it("redirects to /dashboard after a successful registration", async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderRegisterPage(register);

    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(screen.getByText("Dashboard page")).toBeInTheDocument());
  });
});
