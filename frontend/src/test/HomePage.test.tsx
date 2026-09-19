// frontend/src/test/HomePage.test.tsx
// Integration test for HomePage: confirms the full landing page composes
// without crashing and every section is present in the render tree -- a
// regression guard for the composition itself, since each section
// already has its own focused test file.
//
// Landing-page redesign: HomePage now includes AccuracyPreviewSection
// (useAccuracySummary -- needs a QueryClientProvider + a mocked
// global.fetch, same approach as AccuracyPage.test.tsx) and
// AssistantPreviewSection (useAuth -- needs an AuthContext.Provider,
// same raw-context approach ChatWidget.test.tsx already uses rather
// than the real AuthProvider, since no real login flow is under test
// here).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { HomePage } from "@/pages/HomePage";

const UNAUTHENTICATED: AuthContextValue = {
  user: null,
  accessToken: null,
  isAuthenticated: false,
  register: async () => {},
  login: async () => {},
  logout: async () => {},
};

const EMPTY_SUMMARY_RESPONSE = {
  total_evaluated: 0,
  total_pending: 0,
  overall_accuracy_pct: null,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "HOLD", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "SELL", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
  ],
  by_conviction: [],
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderHomePage(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, EMPTY_SUMMARY_RESPONSE)));

  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={UNAUTHENTICATED}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomePage", () => {
  it("renders every landing section", () => {
    renderHomePage();

    expect(
      screen.getByRole("heading", { level: 1, name: /eight agents research, debate, and decide/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/eight specialists, one shared state/i)).toBeInTheDocument();
    expect(screen.getByTestId("accuracy-preview-section")).toBeInTheDocument();
    expect(screen.getByText(/one request, five stages/i)).toBeInTheDocument();
    expect(screen.getByTestId("assistant-preview-section")).toBeInTheDocument();
    expect(screen.getByText(/pick an indian equity/i)).toBeInTheDocument();
    expect(screen.getByText(/built with/i)).toBeInTheDocument();
    expect(screen.getByText(/not investment advice/i)).toBeInTheDocument();
  });

  it("renders exactly one <h1>", () => {
    renderHomePage();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
