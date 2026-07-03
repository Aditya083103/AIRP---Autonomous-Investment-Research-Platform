// frontend/src/test/AnalysisResultPage.test.tsx
// Tests for AnalysisResultPage (T-059). Same FakeWebSocket approach as
// useAnalysisStream.test.ts -- this page calls the real hook (unlike
// AgentProgressBoard, which takes events as plain props), so a fake
// WebSocket global is needed to drive it deterministically.

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
  render(
    <AuthContext.Provider value={AUTH_VALUE}>
      <MemoryRouter initialEntries={[`/analysis/${jobId}/result`]}>
        <Routes>
          <Route path="/analysis/:jobId/result" element={<AnalysisResultPage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
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

  it("shows a completion summary once the final event arrives", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
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
