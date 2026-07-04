// frontend/src/test/AnalysisResultPage.test.tsx
// Tests for AnalysisResultPage (T-059, extended T-060/T-061). Same
// FakeWebSocket approach as useAnalysisStream.test.ts -- this page
// calls the real hook (unlike AgentProgressBoard, which takes events
// as plain props), so a fake WebSocket global is needed to drive it
// deterministically. T-061 adds a QueryClientProvider wrapper (the
// page now also calls useAnalysisResult, a React Query hook, once the
// stream reports completion) and mocks global.fetch for the
// GET /analysis/{job_id}/result call the same way DashboardPage.test.tsx
// mocks GET /analysis/history.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { AnalysisResultPage } from "@/pages/AnalysisResultPage";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {}

  emitMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function lastSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) {
    throw new Error("No FakeWebSocket was constructed");
  }
  return socket;
}

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

function renderResultPage(jobId = "job-1"): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH_VALUE}>
        <MemoryRouter initialEntries={[`/analysis/${jobId}/result`]}>
          <Routes>
            <Route path="/analysis/:jobId/result" element={<AnalysisResultPage />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
});

describe("AnalysisResultPage", () => {
  it("connects using the jobId from the route and the in-memory access token", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderResultPage("11111111-1111-1111-1111-111111111111");

    expect(lastSocket().url).toContain(
      "/api/v1/analysis/11111111-1111-1111-1111-111111111111/stream",
    );
    expect(lastSocket().url).toContain("token=jwt-token");
  });

  it("renders the committee board with all 8 agent cards", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    expect(screen.getByText("Portfolio Manager")).toBeInTheDocument();
    expect(screen.getByText("Fundamental Analyst")).toBeInTheDocument();
  });

  it("shows completion summary and the Investment Memo once the final event arrives", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE)));
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "pdf_export",
        status: "completed",
        output_preview: "Memo generated.",
        progress_percent: 100,
        is_final: true,
      });
    });

    expect(await screen.findByText("Analysis complete.")).toBeInTheDocument();
    expect(await screen.findByTestId("results-panel")).toBeInTheDocument();
    expect(screen.getByText("Infosys shows strong deal momentum.")).toBeInTheDocument();
  });

  it("shows a failure summary when the pipeline terminates with status failed", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "fundamental_analyst",
        status: "failed",
        output_preview: "yFinance rate limit exceeded.",
        progress_percent: 40,
        is_final: true,
      });
    });

    expect(await screen.findByText("This analysis did not complete.")).toBeInTheDocument();
    // The failure message correctly appears twice: once on the failed
    // agent's own card, once in the summary panel below the board.
    expect(screen.getAllByText("yFinance rate limit exceeded.")).toHaveLength(2);
  });

  it("does not fetch the result for a failed analysis", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "fundamental_analyst",
        status: "failed",
        output_preview: "yFinance rate limit exceeded.",
        progress_percent: 40,
        is_final: true,
      });
    });

    await screen.findByText("This analysis did not complete.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an error message if the Investment Memo fails to load", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: "Something broke" })),
    );
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "pdf_export",
        status: "completed",
        output_preview: "Memo generated.",
        progress_percent: 100,
        is_final: true,
      });
    });

    expect(await screen.findByText("Something broke")).toBeInTheDocument();
  });

  it("does not show a completion summary while the job is still running", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    expect(screen.queryByText("Analysis complete.")).not.toBeInTheDocument();
    expect(screen.queryByText("This analysis did not complete.")).not.toBeInTheDocument();
  });

  it("reflects an in-progress agent's output on the board", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "fundamental_analyst",
        status: "running",
        output_preview: "Revenue grew 8% YoY.",
        progress_percent: 20,
        is_final: false,
      });
    });

    await waitFor(() => expect(screen.getByText("Revenue grew 8% YoY.")).toBeInTheDocument());
  });

  it("shows the agent progress board by default", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    expect(screen.getByRole("tab", { name: "Agent progress" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByTestId("debate-viewer")).not.toBeInTheDocument();
  });

  it("switches to the debate transcript when its tab is clicked", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    await userEvent.click(screen.getByRole("tab", { name: "Debate transcript" }));

    expect(screen.getByTestId("debate-viewer")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Debate transcript" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("carries stream events over into the debate transcript tab", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    act(() => {
      lastSocket().emitMessage({
        job_id: "job-1",
        agent: "fundamental_analyst",
        status: "completed",
        output_preview: "Revenue grew 8% YoY.",
        progress_percent: 20,
        is_final: false,
      });
    });

    await userEvent.click(screen.getByRole("tab", { name: "Debate transcript" }));

    expect(await screen.findByText("Revenue grew 8% YoY.")).toBeInTheDocument();
  });
});
