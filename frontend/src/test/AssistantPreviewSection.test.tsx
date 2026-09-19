// frontend/src/test/AssistantPreviewSection.test.tsx
// Tests for AssistantPreviewSection (landing-page redesign): the example
// conversation renders as clearly-labelled static markup (not the live
// ChatWidget), and the CTA adapts to auth state -- dispatches the
// OPEN_CHAT_WIDGET_EVENT for a signed-in visitor (see chatWidgetBus.ts),
// links to /register for an anonymous one.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AssistantPreviewSection } from "@/components/landing/AssistantPreviewSection";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { OPEN_CHAT_WIDGET_EVENT } from "@/lib/chat/chatWidgetBus";

function authValue(isAuthenticated: boolean): AuthContextValue {
  return {
    user: isAuthenticated
      ? {
          id: "1",
          email: "a@example.com",
          display_name: null,
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
        }
      : null,
    accessToken: isAuthenticated ? "jwt-token" : null,
    isAuthenticated,
    register: async () => {},
    login: async () => {},
    logout: async () => {},
  };
}

function renderSection(isAuthenticated: boolean): void {
  render(
    <AuthContext.Provider value={authValue(isAuthenticated)}>
      <MemoryRouter>
        <AssistantPreviewSection />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("AssistantPreviewSection", () => {
  it("labels the sample transcript as an example, not a live conversation", () => {
    renderSection(false);
    expect(screen.getByText(/example conversation/i)).toBeInTheDocument();
  });

  it("shows a message demonstrating it explains but never changes a verdict", () => {
    renderSection(false);
    expect(screen.getByText(/can't issue or revise verdicts/i)).toBeInTheDocument();
  });

  it("links an anonymous visitor to sign up rather than opening a widget that isn't mounted", () => {
    renderSection(false);
    expect(screen.getByRole("link", { name: /sign up to try it/i })).toHaveAttribute(
      "href",
      "/register",
    );
  });

  it("dispatches the open-chat-widget event for a signed-in visitor", async () => {
    renderSection(true);
    const listener = vi.fn();
    window.addEventListener(OPEN_CHAT_WIDGET_EVENT, listener);

    await userEvent.click(screen.getByRole("button", { name: /try the assistant/i }));

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(OPEN_CHAT_WIDGET_EVENT, listener);
  });
});
