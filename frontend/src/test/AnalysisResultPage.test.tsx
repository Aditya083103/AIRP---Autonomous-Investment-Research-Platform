// frontend/src/test/AnalysisResultPage.test.tsx
// Tests for AnalysisResultPage (T-059, extended T-060/T-061/T-062).
// Same FakeWebSocket approach as useAnalysisStream.test.ts -- this
// page calls the real hook (unlike AgentProgressBoard, which takes
// events as plain props), so a fake WebSocket global is needed to
// drive it deterministically. T-061 added a QueryClientProvider
// wrapper (the page calls useAnalysisResult, a React Query hook, once
// the stream reports completion) and mocked global.fetch for the
// GET /analysis/{job_id}/result call. T-062 adds a second, parallel
// query (useAnalysisCharts) on the same completion gate -- mockFetch
// below routes by URL substring so /result and /charts each resolve
// their own response shape instead of one test's single mock
// accidentally serving the wrong body to the other endpoint.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { toastStore } from "@/lib/toastStore";
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

const CHART_DATA_RESPONSE = {
  job_id: "job-1",
  ticker: "INFY.NS",
  company_name: "Infosys",
  price_currency: "INR",
  price_history: [{ date: "2026-06-18", close: 1780.5, volume: 1_000_000 }],
  financials: [{ fiscal_year: "FY 2024", revenue_crores: 153_670.0, net_income_crores: 26_233.0 }],
  valuation: {
    pe_ratio: 24.1,
    sector_avg_pe: 22.5,
    pb_ratio: 8.2,
    sector_avg_pb: 7.9,
    ev_ebitda: 15.3,
    sector_avg_ev_ebitda: 14.8,
    peer_tickers: ["TCS.NS"],
  },
  sentiment: {
    sentiment_score: 0.18,
    sentiment_label: "positive",
    articles_analysed: 19,
    positive_articles: 9,
    negative_articles: 4,
    neutral_articles: 6,
  },
  risk: {
    risk_score: 3,
    governance_risk: 2,
    regulatory_risk: 2,
    financial_risk: 4,
    concentration_risk: 5,
  },
  data_warnings: [],
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

/**
 * Routes a fetch mock's response by URL substring -- /result and
 * /charts each get their own configured status/body, defaulting to a
 * 404 for any URL neither map covers (surfaces a mistaken/missing
 * route immediately instead of silently returning undefined).
 */
function mockFetchByUrl(routes: {
  result?: { status: number; body: unknown };
  charts?: { status: number; body: unknown };
}): ReturnType<typeof vi.fn<[url: string], Promise<Response>>> {
  return vi.fn<[url: string], Promise<Response>>((url) => {
    if (url.includes("/charts") && routes.charts) {
      return Promise.resolve(jsonResponse(routes.charts.status, routes.charts.body));
    }
    if (url.includes("/result") && routes.result) {
      return Promise.resolve(jsonResponse(routes.result.status, routes.result.body));
    }
    return Promise.resolve(jsonResponse(404, { detail: "unmapped URL in test" }));
  });
}

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

function emitFinalEvent(status: "completed" | "failed" = "completed"): void {
  act(() => {
    lastSocket().emitMessage({
      job_id: "job-1",
      agent: status === "completed" ? "pdf_export" : "fundamental_analyst",
      status,
      output_preview: status === "completed" ? "Memo generated." : "yFinance rate limit exceeded.",
      progress_percent: status === "completed" ? 100 : 40,
      is_final: true,
    });
  });
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
  toastStore.clear();
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

  it("shows the results skeleton while the memo is pending", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByTestId("results-panel-skeleton")).toBeInTheDocument();
  });

  it("shows the charts skeleton once the memo loaded but charts are still pending", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("/result")) {
          return Promise.resolve(jsonResponse(200, RESULT_RESPONSE));
        }
        return new Promise(() => {});
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByTestId("results-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("charts-panel-skeleton")).toBeInTheDocument();
  });

  it("shows completion summary and the Investment Memo once the final event arrives", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      mockFetchByUrl({
        result: { status: 200, body: RESULT_RESPONSE },
        charts: { status: 200, body: CHART_DATA_RESPONSE },
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByText("Analysis complete.")).toBeInTheDocument();
    expect(await screen.findByTestId("results-panel")).toBeInTheDocument();
    expect(screen.getByText("Infosys shows strong deal momentum.")).toBeInTheDocument();
  });

  it("shows the charts panel once the final event arrives", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      mockFetchByUrl({
        result: { status: 200, body: RESULT_RESPONSE },
        charts: { status: 200, body: CHART_DATA_RESPONSE },
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByTestId("charts-panel")).toBeInTheDocument();
    expect(screen.getByTestId("stock-price-chart")).toBeInTheDocument();
    expect(screen.getByTestId("risk-radar-chart")).toBeInTheDocument();
  });

  it("shows a failure summary when the pipeline terminates with status failed", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    emitFinalEvent("failed");

    expect(await screen.findByText("This analysis did not complete.")).toBeInTheDocument();
    // The failure message correctly appears twice: once on the failed
    // agent's own card, once in the summary panel below the board.
    expect(screen.getAllByText("yFinance rate limit exceeded.")).toHaveLength(2);
  });

  it("does not fetch the result or the charts for a failed analysis", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const fetchMock = mockFetchByUrl({
      result: { status: 200, body: RESULT_RESPONSE },
      charts: { status: 200, body: CHART_DATA_RESPONSE },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderResultPage();

    emitFinalEvent("failed");

    await screen.findByText("This analysis did not complete.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an error message if the Investment Memo fails to load", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      mockFetchByUrl({
        result: { status: 500, body: { detail: "Something broke" } },
        charts: { status: 200, body: CHART_DATA_RESPONSE },
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByText("Something broke")).toBeInTheDocument();
  });

  it("shows an error message if the charts fail to load, without blocking the memo", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      mockFetchByUrl({
        result: { status: 200, body: RESULT_RESPONSE },
        charts: { status: 500, body: { detail: "Charts backend broke" } },
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByTestId("results-panel")).toBeInTheDocument();
    expect(await screen.findByText("Charts backend broke")).toBeInTheDocument();
    expect(screen.queryByTestId("charts-panel")).not.toBeInTheDocument();
  });

  it("shows a warnings banner in the charts panel when a source is degraded", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const degradedCharts = {
      ...CHART_DATA_RESPONSE,
      valuation: null,
      data_warnings: ["Valuation data was not available for this analysis."],
    };
    vi.stubGlobal(
      "fetch",
      mockFetchByUrl({
        result: { status: 200, body: RESULT_RESPONSE },
        charts: { status: 200, body: degradedCharts },
      }),
    );
    renderResultPage();

    emitFinalEvent("completed");

    expect(await screen.findByTestId("charts-panel-warnings")).toBeInTheDocument();
    expect(screen.getByTestId("sentiment-gauge-chart")).toBeInTheDocument();
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

  it("shows a toast when the stream closes with an unauthorized code (T-066)", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderResultPage();

    act(() => {
      lastSocket().onclose?.({ code: 4401 });
    });

    await waitFor(() =>
      expect(toastStore.getSnapshot()).toContainEqual(
        expect.objectContaining({
          tone: "error",
          message: "Not authorized to view this analysis (invalid or expired token).",
        }),
      ),
    );
  });
});
