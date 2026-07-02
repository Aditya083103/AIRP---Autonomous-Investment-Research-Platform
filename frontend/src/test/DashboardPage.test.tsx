// frontend/src/test/DashboardPage.test.tsx
// Tests for DashboardPage (T-057). Wraps a QueryClientProvider (fresh
// client per test, retries disabled so a failure test resolves
// immediately) + a fake AuthContext + MemoryRouter, and mocks
// global.fetch the same way authApi.test.ts / analysisApi.test.ts do --
// no real network call is made.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { DashboardPage } from "@/pages/DashboardPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AUTH_VALUE: AuthContextValue = {
  user: {
    id: "1",
    email: "a@example.com",
    display_name: "Aditya",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  accessToken: "jwt-token",
  isAuthenticated: true,
  register: async () => {},
  login: async () => {},
  logout: async () => {},
};

function renderDashboard(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH_VALUE}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

function historyResponse(overrides: Record<string, unknown> = {}): unknown {
  return {
    items: [
      {
        job_id: "11111111-1111-1111-1111-111111111111",
        company_name: "Infosys",
        ticker: "INFY.NS",
        exchange: "NSE",
        status: "completed",
        requested_at: "2026-01-01T00:00:00Z",
        completed_at: "2026-01-01T00:01:00Z",
        verdict: "BUY",
        conviction_score: 8,
      },
      {
        job_id: "22222222-2222-2222-2222-222222222222",
        company_name: "Tata Consultancy Services",
        ticker: "TCS.NS",
        exchange: "NSE",
        status: "completed",
        requested_at: "2026-01-02T00:00:00Z",
        completed_at: "2026-01-02T00:01:00Z",
        verdict: "SELL",
        conviction_score: 3,
      },
    ],
    total_count: 2,
    limit: 20,
    offset: 0,
    has_more: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DashboardPage", () => {
  it("greets the user by display name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, historyResponse())));
    renderDashboard();

    expect(
      await screen.findByRole("heading", { name: /welcome back, aditya/i }),
    ).toBeInTheDocument();
  });

  it("loads and renders history rows from the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, historyResponse())));
    renderDashboard();

    expect(await screen.findByText("Infosys")).toBeInTheDocument();
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
  });

  it("colour-codes BUY and SELL verdict badges", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, historyResponse())));
    renderDashboard();

    const buyBadge = await screen.findByText("BUY");
    const sellBadge = await screen.findByText("SELL");
    expect(buyBadge.className).toContain("bg-verdict-buy");
    expect(sellBadge.className).toContain("bg-verdict-sell");
  });

  it("shows an empty state when there is no history yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, historyResponse({ items: [], total_count: 0 }))),
    );
    renderDashboard();

    expect(await screen.findByText(/haven't run an analysis yet/i)).toBeInTheDocument();
  });

  it("shows an error message when the request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: "Something broke" })),
    );
    renderDashboard();

    expect(await screen.findByText("Something broke")).toBeInTheDocument();
  });

  it("filters the loaded rows by company name as the user types", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, historyResponse())));
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByText("Infosys");
    await user.type(screen.getByLabelText("Search by company"), "infosys");

    expect(screen.getByText("Infosys")).toBeInTheDocument();
    expect(screen.queryByText("Tata Consultancy Services")).not.toBeInTheDocument();
  });

  it("disables Previous on the first page and Next when there is no more data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, historyResponse())));
    renderDashboard();

    await screen.findByText("Infosys");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("requests the next page when Next is clicked and more data exists", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, historyResponse({ has_more: true })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderDashboard();

    await screen.findByText("Infosys");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.at(-1) as [string, RequestInit];
      expect(lastCall[0]).toContain("offset=20");
    });
  });
});
