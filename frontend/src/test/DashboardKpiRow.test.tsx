// frontend/src/test/DashboardKpiRow.test.tsx
// Tests for DashboardKpiRow (B11). Stubs prefers-reduced-motion to
// `true` throughout -- AnimatedNumber counts up from 0 on mount when
// motion is allowed (see that component's own tests for that behaviour),
// which would make a synchronous getByText("42") assertion here flaky;
// this file's job is confirming the *right numbers* are wired in, not
// re-testing AnimatedNumber's own animation, so the reduced-motion path
// (immediate final value, no tween) keeps these assertions deterministic.

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardKpiRow } from "@/components/dashboard/DashboardKpiRow";
import { type HistoryEntryResponse } from "@/types/analysis";

function stubReducedMotion(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

function makeEntry(overrides: Partial<HistoryEntryResponse> = {}): HistoryEntryResponse {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    company_name: "Infosys",
    ticker: "INFY.NS",
    exchange: "NSE",
    status: "completed",
    requested_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:01:00Z",
    verdict: "BUY",
    conviction_score: 8,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DashboardKpiRow", () => {
  it("renders the container", () => {
    stubReducedMotion();
    render(<DashboardKpiRow items={[]} totalCount={0} />);
    expect(screen.getByTestId("dashboard-kpi-row")).toBeInTheDocument();
  });

  it("renders total analyses and completed-on-page counts", () => {
    stubReducedMotion();
    const items = [
      makeEntry({ job_id: "a", status: "completed" }),
      makeEntry({ job_id: "b", status: "running", verdict: null, conviction_score: null }),
    ];
    render(<DashboardKpiRow items={items} totalCount={42} />);

    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders the most recent decided verdict's badge and company name", () => {
    stubReducedMotion();
    const items = [makeEntry({ verdict: "SELL", company_name: "Tata Motors" })];
    render(<DashboardKpiRow items={items} totalCount={1} />);

    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("Tata Motors")).toBeInTheDocument();
  });

  it("shows a placeholder dash when nothing on this page has a verdict yet", () => {
    stubReducedMotion();
    const items = [makeEntry({ status: "running", verdict: null, conviction_score: null })];
    render(<DashboardKpiRow items={items} totalCount={1} />);

    expect(screen.getByText("--")).toBeInTheDocument();
  });
});
