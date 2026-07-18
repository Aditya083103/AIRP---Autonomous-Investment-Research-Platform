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
  fundamental_years_available: null,
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

  describe("data-completeness note (T-084)", () => {
    it("shows the note when fewer than 4 years of data were available", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse(200, { ...RESULT_RESPONSE, fundamental_years_available: 2 }),
          ),
      );
      renderMemoPage();

      expect(await screen.findByTestId("data-completeness-note")).toHaveTextContent(
        "Fundamental analysis based on 2 of 4 years of available financial data.",
      );
    });

    it("does not show the note when all 4 years of data were available", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse(200, { ...RESULT_RESPONSE, fundamental_years_available: 4 }),
          ),
      );
      renderMemoPage();

      await screen.findByTestId("verdict-panel");
      expect(screen.queryByTestId("data-completeness-note")).not.toBeInTheDocument();
    });

    it("does not show the note when years_available is unknown (null)", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse(200, { ...RESULT_RESPONSE, fundamental_years_available: null }),
          ),
      );
      renderMemoPage();

      await screen.findByTestId("verdict-panel");
      expect(screen.queryByTestId("data-completeness-note")).not.toBeInTheDocument();
    });

    it("shows the note for a single year of available data with correct singular-safe wording", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse(200, { ...RESULT_RESPONSE, fundamental_years_available: 1 }),
          ),
      );
      renderMemoPage();

      expect(await screen.findByTestId("data-completeness-note")).toHaveTextContent(
        "based on 1 of 4 years",
      );
    });
  });
});
