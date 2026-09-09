// frontend/src/test/ResetPasswordPage.test.tsx
// Tests for ResetPasswordPage (B6). Stubs global.fetch directly (no
// AuthContext needed -- POST /auth/password-reset/confirm returns no
// token; this page never touches useAuth()) and reads `?token=` off
// MemoryRouter's initialEntries, the same way a real emailed link
// would arrive.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordPage } from "@/pages/ResetPasswordPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderResetPasswordPage(path = "/reset-password?token=raw-token-value"): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<p>Login page</p>} />
        <Route path="/forgot-password" element={<p>Forgot password page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ResetPasswordPage without a token", () => {
  it("shows an invalid-link state instead of a form when ?token= is missing", () => {
    renderResetPasswordPage("/reset-password");

    expect(screen.getByText("Invalid reset link")).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("links to /forgot-password to request a new link", () => {
    renderResetPasswordPage("/reset-password");

    expect(screen.getByRole("link", { name: /request a password reset/i })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("shows an invalid-link state when ?token= is present but empty", () => {
    renderResetPasswordPage("/reset-password?token=");

    expect(screen.getByText("Invalid reset link")).toBeInTheDocument();
  });
});

describe("ResetPasswordPage with a token", () => {
  it("shows validation errors when submitted empty", async () => {
    const user = userEvent.setup();
    renderResetPasswordPage();

    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(await screen.findByText("Password must be at least 8 characters.")).toBeInTheDocument();
  });

  it("rejects mismatched passwords", async () => {
    const user = userEvent.setup();
    renderResetPasswordPage();

    await user.type(screen.getByLabelText("New password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm new password"), "different-password");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
  });

  it("submits the token from the URL and the new password, then redirects to /login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { message: "Your password has been reset." }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderResetPasswordPage();

    await user.type(screen.getByLabelText("New password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm new password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ token: "raw-token-value", new_password: "correct-horse-battery" });
  });

  it("shows the backend's error message for an invalid/expired token, without redirecting", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(400, {
          detail: "This reset link is invalid or has expired. Please request a new one.",
        }),
      ),
    );
    const user = userEvent.setup();
    renderResetPasswordPage();

    await user.type(screen.getByLabelText("New password"), "correct-horse-battery");
    await user.type(screen.getByLabelText("Confirm new password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /reset password/i }));

    expect(
      await screen.findByText(
        "This reset link is invalid or has expired. Please request a new one.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});
