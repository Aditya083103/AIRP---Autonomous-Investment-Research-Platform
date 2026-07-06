// frontend/src/test/ComparePage.test.tsx
// Tests for ComparePage (T-064). Same FakeWebSocket approach
// AnalysisResultPage.test.tsx already uses, doubled: two sockets (one
// per job) drive CompanyAnalysisPanel's two independent
// useAnalysisStream instances, and fetch is routed by job_id substring
// so /analysis/start, /result, and /charts each resolve the right
// company's payload regardless of call order.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { toastStore } from "@/lib/toastStore";
import { ComparePage } from "@/pages/ComparePage";

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

function socketForJob(jobId: string): FakeWebSocket {
  const socket = FakeWebSocket.instances.find((instance) => instance.url.includes(jobId));
  if (!socket) {
    throw new Error(`No FakeWebSocket connected for ${jobId}`);
  }
  return socket;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const JOB_A = "aaaaaaaa-1111-1111-1111-111111111111";
const JOB_B = "bbbbbbbb-2222-2222-2222-222222222222";

function makeDecision(jobId: string, overrides: Record<string, unknown> = {}) {
  return {
    agent_name: "portfolio_manager",
    analysis_id: jobId,
    company_name: jobId === JOB_A ? "Tata Consultancy Services" : "Infosys",
    ticker: jobId === JOB_A ? "TCS.NS" : "INFY.NS",
    generated_at: "2026-06-15T10:30:00Z",
    error: null,
    verdict: jobId === JOB_A ? "BUY" : "HOLD",
    conviction_score: jobId === JOB_A ? 8 : 5,
    price_target: null,
    time_horizon: "12 months",
    executive_summary: "",
    investment_thesis: "",
    bull_case: "",
    bear_case: "",
    risk_summary: "",
    valuation_summary: "",
    key_risks: [],
    key_catalysts: [],
    contrarian_response: "",
    debate_rounds_used: 2,
    agent_weights: {},
    summary: "",
    ...overrides,
  };
}

function makeCharts(jobId: string) {
  return {
    job_id: jobId,
    ticker: jobId === JOB_A ? "TCS.NS" : "INFY.NS",
    company_name: jobId === JOB_A ? "Tata Consultancy Services" : "Infosys",
    price_currency: "INR",
    price_history: [],
    financials: [],
    valuation: null,
    sentiment: null,
    risk: null,
    data_warnings: [],
  };
}

type FetchMock = ReturnType<typeof vi.fn<[url: string, init?: RequestInit], Promise<Response>>>;

function mockFetch(): FetchMock {
  let startCallCount = 0;
  return vi.fn<[url: string, init?: RequestInit], Promise<Response>>((url) => {
    if (url.includes("/analysis/start")) {
      startCallCount += 1;
      const jobId = startCallCount === 1 ? JOB_A : JOB_B;
      return Promise.resolve(
        jsonResponse(202, {
          job_id: jobId,
          status: "pending",
          company_name: jobId === JOB_A ? "Tata Consultancy Services" : "Infosys",
          ticker: jobId === JOB_A ? "TCS.NS" : "INFY.NS",
          exchange: "NSE",
        }),
      );
    }
    if (url.includes(`/${JOB_A}/result`)) {
      return Promise.resolve(jsonResponse(200, makeDecision(JOB_A)));
    }
    if (url.includes(`/${JOB_B}/result`)) {
      return Promise.resolve(jsonResponse(200, makeDecision(JOB_B)));
    }
    if (url.includes(`/${JOB_A}/charts`)) {
      return Promise.resolve(jsonResponse(200, makeCharts(JOB_A)));
    }
    if (url.includes(`/${JOB_B}/charts`)) {
      return Promise.resolve(jsonResponse(200, makeCharts(JOB_B)));
    }
    return Promise.resolve(jsonResponse(404, { detail: "unmapped URL in test" }));
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

function renderComparePage(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={AUTH_VALUE}>
        <MemoryRouter initialEntries={["/compare"]}>
          <Routes>
            <Route path="/compare" element={<ComparePage />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

async function submitComparison(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const companyACombo = screen.getByRole("combobox", { name: "Company A" });
  await user.click(companyACombo);
  await user.type(companyACombo, "TCS");
  await user.click(screen.getByRole("option", { name: /tcs/i }));

  const companyBCombo = screen.getByRole("combobox", { name: "Company B" });
  await user.click(companyBCombo);
  await user.type(companyBCombo, "Infosys");
  await user.click(screen.getByRole("option", { name: /infosys/i }));

  await user.click(screen.getByRole("button", { name: /compare companies/i }));
}

function completeJob(jobId: string): void {
  act(() => {
    socketForJob(jobId).emitMessage({
      job_id: jobId,
      agent: "portfolio_manager",
      status: "completed",
      output_preview: "Memo generated.",
      progress_percent: 100,
      is_final: true,
    });
  });
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
  toastStore.clear();
});

describe("ComparePage", () => {
  it("shows the two-company form initially", () => {
    renderComparePage();

    expect(screen.getByTestId("compare-input-form")).toBeInTheDocument();
  });

  it("starts two parallel analyses and shows a progress panel per company", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("fetch", mockFetch());
    const user = userEvent.setup();
    renderComparePage();

    await submitComparison(user);

    await waitFor(() => expect(screen.getByTestId("compare-panels")).toBeInTheDocument());
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
    expect(screen.getByText("Infosys")).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("renders the comparison table with the winning cells once both analyses finish", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("fetch", mockFetch());
    const user = userEvent.setup();
    renderComparePage();

    await submitComparison(user);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));

    completeJob(JOB_A);
    completeJob(JOB_B);

    expect(await screen.findByTestId("comparison-table")).toBeInTheDocument();
    // Company A (TCS) has the higher conviction score and BUY verdict.
    expect(screen.getByTestId("cell-verdict-a")).toHaveTextContent("Winner");
    expect(screen.getByTestId("cell-conviction_score-a")).toHaveTextContent("Winner");
  });

  it("lets the user compare again after seeing results", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal("fetch", mockFetch());
    const user = userEvent.setup();
    renderComparePage();

    await submitComparison(user);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    completeJob(JOB_A);
    completeJob(JOB_B);
    await screen.findByTestId("comparison-table");

    await user.click(screen.getByRole("button", { name: /compare again/i }));

    expect(screen.getByTestId("compare-input-form")).toBeInTheDocument();
  });

  it("shows an inline error and a toast when starting the comparison fails (T-066)", async () => {
    // mockImplementation (not mockResolvedValue) so each of the two
    // concurrent fetch calls -- ComparePage's handleSubmit fires both
    // starts via Promise.all -- gets its own fresh Response object.
    // mockResolvedValue resolves to a single shared Response instance;
    // a Response body can only be read once, so the second concurrent
    // `.json()` call would throw "body stream already read" instead of
    // parsing the intended payload.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(jsonResponse(500, { detail: "Analysis service unavailable" })),
        ),
    );
    const user = userEvent.setup();
    renderComparePage();

    await submitComparison(user);

    expect(await screen.findByText("Analysis service unavailable")).toBeInTheDocument();
    expect(toastStore.getSnapshot()).toContainEqual(
      expect.objectContaining({ tone: "error", message: "Analysis service unavailable" }),
    );
  });
});
