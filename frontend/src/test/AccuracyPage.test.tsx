// frontend/src/test/AccuracyPage.test.tsx
// Tests for AccuracyPage (T-092). Same QueryClientProvider + mocked
// global.fetch approach as DashboardPage.test.tsx -- no AuthContext
// wrapper is needed here (unlike DashboardPage), since this route is
// public and neither of its two hooks reads accessToken at all.
//
// mockFetch below routes by URL substring so /accuracy/summary and
// /accuracy/history each resolve their own response shape, the same
// "route by URL substring" approach AnalysisResultPage.test.tsx already
// uses for its own two parallel queries (T-062's /result vs /charts).
//
// Acceptance criteria covered here (from the task spec):
//   * "/accuracy route renders three charts from live API data" --
//     "renders all three charts once both queries resolve"
//   * "loading/empty states handled" -- the skeleton-while-loading test,
//     the error-message test, and every chart's own empty-state
//     fallback (exercised via AccuracyPanel.test.tsx and each chart's
//     own test file) collectively cover this
//   * "responsive" is a Tailwind breakpoint concern
//     (AccuracyPanel.tsx's `sm:grid-cols-3` / `md:grid-cols-2`), not
//     something jsdom can assert on -- verified by manual/visual review
//     per this task's workflow doc, the same way ChartsPanel's own
//     `md:grid-cols-3` responsiveness was verified for T-062

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccuracyPage } from "@/pages/AccuracyPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const EMPTY_SUMMARY_RESPONSE = {
  total_evaluated: 0,
  total_pending: 0,
  overall_accuracy_pct: null,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "HOLD", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "SELL", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
  ],
  by_conviction: [
    {
      bucket: "low",
      label: "Low (1-3)",
      min_score: 1,
      max_score: 3,
      evaluated_count: 0,
      correct_count: 0,
      accuracy_pct: null,
    },
    {
      bucket: "medium",
      label: "Medium (4-6)",
      min_score: 4,
      max_score: 6,
      evaluated_count: 0,
      correct_count: 0,
      accuracy_pct: null,
    },
    {
      bucket: "high",
      label: "High (7-10)",
      min_score: 7,
      max_score: 10,
      evaluated_count: 0,
      correct_count: 0,
      accuracy_pct: null,
    },
  ],
};

const POPULATED_SUMMARY_RESPONSE = {
  ...EMPTY_SUMMARY_RESPONSE,
  total_evaluated: 10,
  total_pending: 2,
  overall_accuracy_pct: 70.0,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 5, correct_count: 4, accuracy_pct: 80.0 },
    { verdict: "HOLD", evaluated_count: 3, correct_count: 2, accuracy_pct: 66.67 },
    { verdict: "SELL", evaluated_count: 2, correct_count: 1, accuracy_pct: 50.0 },
  ],
};

const EMPTY_HISTORY_RESPONSE = {
  items: [],
  total_count: 0,
  limit: 100,
  offset: 0,
  has_more: false,
};

const POPULATED_HISTORY_RESPONSE = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      analysis_id: "22222222-2222-2222-2222-222222222222",
      ticker: "TCS.NS",
      verdict: "BUY",
      conviction_score: 8,
      price_at_verdict: 3000.0,
      verdict_date: "2026-01-01T00:00:00Z",
      evaluation_horizon_days: 90,
      price_at_evaluation: 3200.0,
      price_change_pct: 6.6667,
      directional_correct: true,
      evaluated_at: "2026-04-01T00:00:00Z",
    },
  ],
  total_count: 1,
  limit: 100,
  offset: 0,
  has_more: false,
};

function mockFetch(options: {
  summary?: Response | (() => Promise<Response>);
  history?: Response | (() => Promise<Response>);
}): void {
  const fetchMock = vi.fn().mockImplementation(async (input: string) => {
    const url = typeof input === "string" ? input : String(input);
    if (url.includes("/accuracy/summary")) {
      const summary = options.summary ?? jsonResponse(200, EMPTY_SUMMARY_RESPONSE);
      return typeof summary === "function" ? await summary() : summary;
    }
    if (url.includes("/accuracy/history")) {
      const history = options.history ?? jsonResponse(200, EMPTY_HISTORY_RESPONSE);
      return typeof history === "function" ? await history() : history;
    }
    throw new Error(`Unexpected fetch URL in test: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
}

function renderPage(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AccuracyPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AccuracyPage", () => {
  it("renders the page heading", () => {
    mockFetch({});
    renderPage();

    expect(
      screen.getByRole("heading", { name: /how right has the committee actually been/i }),
    ).toBeInTheDocument();
  });

  it("shows a skeleton while summary and history are both loading", () => {
    mockFetch({
      summary: () => new Promise(() => {}),
      history: () => new Promise(() => {}),
    });
    renderPage();

    expect(screen.getByTestId("accuracy-panel-skeleton")).toBeInTheDocument();
  });

  it("keeps showing the skeleton while only one of the two queries has resolved", async () => {
    let resolveSummary: (() => void) | undefined;
    mockFetch({
      summary: () =>
        new Promise((resolve) => {
          resolveSummary = () => resolve(jsonResponse(200, EMPTY_SUMMARY_RESPONSE));
        }),
      history: () => new Promise(() => {}),
    });
    renderPage();

    expect(screen.getByTestId("accuracy-panel-skeleton")).toBeInTheDocument();

    resolveSummary?.();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByTestId("accuracy-panel-skeleton")).toBeInTheDocument();
  });

  it("renders all three charts once both queries resolve with populated data", async () => {
    mockFetch({
      summary: jsonResponse(200, POPULATED_SUMMARY_RESPONSE),
      history: jsonResponse(200, POPULATED_HISTORY_RESPONSE),
    });
    renderPage();

    expect(await screen.findByTestId("accuracy-panel")).toBeInTheDocument();
    expect(screen.getByTestId("accuracy-trend-chart")).toBeInTheDocument();
    expect(screen.getByTestId("verdict-accuracy-chart")).toBeInTheDocument();
    expect(screen.getByTestId("conviction-accuracy-scatter-chart")).toBeInTheDocument();
  });

  it("renders the panel's own empty states for a brand-new, all-zero platform", async () => {
    mockFetch({
      summary: jsonResponse(200, EMPTY_SUMMARY_RESPONSE),
      history: jsonResponse(200, EMPTY_HISTORY_RESPONSE),
    });
    renderPage();

    expect(await screen.findByTestId("accuracy-panel")).toBeInTheDocument();
    expect(screen.getByText("--")).toBeInTheDocument();
    expect(screen.getAllByText(/no verdicts have been scored yet/i).length).toBeGreaterThan(0);
  });

  it("shows an error message when the summary request fails", async () => {
    mockFetch({
      summary: jsonResponse(500, { detail: "Summary is temporarily unavailable" }),
      history: jsonResponse(200, EMPTY_HISTORY_RESPONSE),
    });
    renderPage();

    expect(await screen.findByText("Summary is temporarily unavailable")).toBeInTheDocument();
  });

  it("shows an error message when the history request fails", async () => {
    mockFetch({
      summary: jsonResponse(200, EMPTY_SUMMARY_RESPONSE),
      history: jsonResponse(500, { detail: "History is temporarily unavailable" }),
    });
    renderPage();

    expect(await screen.findByText("History is temporarily unavailable")).toBeInTheDocument();
  });

  it("does not render the panel while either query has an outstanding error", async () => {
    mockFetch({
      summary: jsonResponse(500, { detail: "boom" }),
      history: jsonResponse(200, EMPTY_HISTORY_RESPONSE),
    });
    renderPage();

    await screen.findByRole("alert");
    expect(screen.queryByTestId("accuracy-panel")).not.toBeInTheDocument();
  });
});
