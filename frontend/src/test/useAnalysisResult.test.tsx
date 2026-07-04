// frontend/src/test/useAnalysisResult.test.tsx
// Tests for useAnalysisResult (T-061). Same renderHook + QueryClientProvider
// wrapper approach as any other React Query hook test in this codebase
// (see useAnalysisHistory's consumers in DashboardPage.test.tsx) --
// global.fetch is mocked so no real network call is made.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAnalysisResult } from "@/hooks/useAnalysisResult";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const RESULT_RESPONSE = {
  agent_name: "portfolio_manager",
  analysis_id: "11111111-1111-1111-1111-111111111111",
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

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAnalysisResult", () => {
  it("does not fetch when enabled is false", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(
      () => useAnalysisResult({ jobId: "job-1", accessToken: "jwt-token", enabled: false }),
      { wrapper },
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not fetch when accessToken is null, even if enabled is true", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAnalysisResult({ jobId: "job-1", accessToken: null, enabled: true }), {
      wrapper,
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches and resolves with the InvestmentDecisionResponse once enabled", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAnalysisResult({ jobId: "job-1", accessToken: "jwt-token", enabled: true }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.data).toEqual(RESULT_RESPONSE));
  });

  it("surfaces a 409 (not ready) response as an error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "Analysis is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAnalysisResult({ jobId: "job-1", accessToken: "jwt-token", enabled: true }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
