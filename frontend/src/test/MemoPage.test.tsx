// frontend/src/test/MemoPage.test.tsx
// Tests for MemoPage (T-063): fetches and renders the full
// InvestmentDecisionResponse via useAnalysisResult, renders every
// section collapsibly (defaulting open), shows the toolbar, and
// surfaces a load error the same way AnalysisResultPage does.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { MemoPage } from "@/pages/MemoPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const RESULT_RESPONSE = {
  agent_name: "portfolio_manager",
  analysis_id: "job-1",
  company_name: "Infosys",
  ticker: "INFY.NS",
  generated_at: "2026-06-15T10:30:00Z",
  error: null,
  verdict: "BUY",
  conviction_score: 8,
  price_target: "₹1,800 (12-month)",
  time_horizon: "12 months",
  executive_summary: "Infosys shows strong deal momentum.",
  investment_thesis: "Digital transformation demand supports growth.",
  bull_case: "Large deal wins accelerating.",
  bear_case: "Margin pressure from wage hikes.",
  risk_summary: "Client concentration in BFSI and manufacturing.",
  valuation_summary: "Trading below historical average multiples.",
  key_risks: ["Client concentration"],
  key_catalysts: ["Large deal pipeline"],
  contrarian_response: "Margin concern addressed by cost optimisation plan.",
  debate_rounds_used: 2,
  agent_weights: { fundamental_analyst: 0.3 },
  summary: "Infosys: BUY with conviction 8/10.",
};

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

function renderMemoPage(jobId = "job-1"): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH_VALUE}>
        <MemoryRouter initialEntries={[`/analysis/${jobId}/memo`]}>
          <Routes>
            <Route path="/analysis/:jobId/memo" element={<MemoPage />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MemoPage", () => {
  it("shows a loading state before the result resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    renderMemoPage();

    expect(screen.getByText("Loading the Investment Memo…")).toBeInTheDocument();
  });

  it("renders the memo toolbar and every memo section once loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE)));
    renderMemoPage();

    expect(await screen.findByTestId("verdict-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("memo-toolbar")).toBeInTheDocument();
    expect(screen.getByText("Executive summary")).toBeInTheDocument();
    expect(screen.getByText("Infosys shows strong deal momentum.")).toBeInTheDocument();
    expect(screen.getByText("Investment thesis")).toBeInTheDocument();
    expect(screen.getByTestId("bull-bear-panel")).toBeInTheDocument();
    expect(screen.getByTestId("key-risks-list")).toBeInTheDocument();
    expect(screen.getByText("Valuation")).toBeInTheDocument();
    expect(screen.getByText(/Contrarian resolution \(2 debate rounds\)/)).toBeInTheDocument();
    expect(screen.getByTestId("agent-weights-panel")).toBeInTheDocument();
  });

  it("shows the company name and ticker in the page heading once loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE)));
    renderMemoPage();

    expect(await screen.findByText("Infosys (INFY.NS)")).toBeInTheDocument();
  });

  it("shows an error message if the memo fails to load", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: "Something broke" })),
    );
    renderMemoPage();

    expect(await screen.findByText("Something broke")).toBeInTheDocument();
  });

  it("starts the agent-weighting section collapsed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE)));
    renderMemoPage();

    await screen.findByTestId("memo-page");
    const toggle = await screen.findByRole("button", { name: /Agent weighting/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
