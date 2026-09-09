// frontend/src/test/dashboardKpis.test.ts
// Tests for src/lib/dashboard/dashboardKpis.ts (B11). Pure-function
// tests with plain fixture arrays -- mirrors src/test/rollingAccuracy.
// test.ts's "computation separate from rendering" test style.

import { describe, expect, it } from "vitest";

import { buildDashboardKpis } from "@/lib/dashboard/dashboardKpis";
import { type HistoryEntryResponse } from "@/types/analysis";

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

describe("buildDashboardKpis", () => {
  it("returns zero/null KPIs for an empty page", () => {
    expect(buildDashboardKpis([], 0)).toEqual({
      totalAnalyses: 0,
      completedOnPage: 0,
      mostRecentDecided: null,
    });
  });

  it("uses total_count as-is for totalAnalyses, independent of the page's own length", () => {
    const kpis = buildDashboardKpis([makeEntry()], 137);
    expect(kpis.totalAnalyses).toBe(137);
  });

  it("counts only completed items on this page", () => {
    const items = [
      makeEntry({ job_id: "a", status: "completed" }),
      makeEntry({ job_id: "b", status: "running", verdict: null, conviction_score: null }),
      makeEntry({ job_id: "c", status: "failed", verdict: null, conviction_score: null }),
      makeEntry({ job_id: "d", status: "completed" }),
    ];
    expect(buildDashboardKpis(items, 4).completedOnPage).toBe(2);
  });

  it("picks the first item with a non-null verdict as the most recent decided one", () => {
    const items = [
      makeEntry({ job_id: "newest", status: "running", verdict: null, conviction_score: null }),
      makeEntry({ job_id: "next", company_name: "Tata Motors", verdict: "SELL" }),
      makeEntry({ job_id: "oldest", company_name: "Wipro", verdict: "HOLD" }),
    ];

    const kpis = buildDashboardKpis(items, 3);

    expect(kpis.mostRecentDecided).toEqual({ companyName: "Tata Motors", verdict: "SELL" });
  });

  it("returns null for mostRecentDecided when no item on this page has a verdict yet", () => {
    const items = [
      makeEntry({ status: "running", verdict: null, conviction_score: null }),
      makeEntry({ status: "pending", verdict: null, conviction_score: null }),
    ];
    expect(buildDashboardKpis(items, 2).mostRecentDecided).toBeNull();
  });
});
