// frontend/src/test/ForgotPasswordPage.test.tsx
// Tests for ForgotPasswordPage (B6). Stubs global.fetch directly (no
// AuthContext needed -- this page never touches useAuth(), it calls
// src/api/auth.ts's requestPasswordReset directly), the same pattern
// test/analysisApi.test.ts-adjacent page tests already use.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderForgotPasswordPage(): void {
  render(
    <MemoryRouter initialEntries={["/forgot-password"]}>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/login" element={<p>Login page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ForgotPasswordPage", () => {
  it("shows a validation error when submitted with no email", async () => {
    const user = userEvent.setup();
    renderForgotPasswordPage();

    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByText("Email is required.")).toBeInTheDocument();
  });

  it("shows a validation error for a malformed email", async () => {
    const user = userEvent.setup();
    renderForgotPasswordPage();

    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
  });

  it("shows the same success state for any submitted email (anti-enumeration)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { message: "generic message" }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderForgotPasswordPage();

    await user.type(screen.getByLabelText("Email"), "whoever@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByText("Check your email")).toBeInTheDocument();
  });

  it("shows a form error only on a genuine request failure, not on a 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const user = userEvent.setup();
    renderForgotPasswordPage();

    await user.type(screen.getByLabelText("Email"), "whoever@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(
      await screen.findByText("Could not send the reset link. Please try again."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Check your email")).not.toBeInTheDocument();
  });

  it("links back to /login from both the form state and the success state", async () => {
    const user = userEvent.setup();
    renderForgotPasswordPage();

    expect(screen.getByRole("link", { name: /log in/i })).toHaveAttribute("href", "/login");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { message: "generic message" })),
    );
    await user.type(screen.getByLabelText("Email"), "whoever@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));
    await waitFor(() => expect(screen.getByText("Check your email")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: /log in/i })).toHaveAttribute("href", "/login");
  });
});
