// frontend/src/lib/dashboard/dashboardKpis.ts
// AIRP -- Dashboard KPI card data (B11)
//
// Turns a page of HistoryEntryResponse rows (GET /api/v1/analysis/
// history) into the KPI tiles DashboardKpiRow.tsx renders above
// HistoryTable. Deliberately avoids any verdict-breakdown aggregate
// (e.g. "N BUY calls out of M") -- the endpoint paginates, so a
// page-scoped count of BUY/HOLD/SELL would misrepresent the account's
// whole history the moment there is more than one page, and this
// codebase's established convention (see backend/routers/accuracy.py's
// AccuracyHistoryEntryResponse docstring, B7's awaitingVerdicts.ts) is
// that a KPI must be honest about its own scope or not shown at all.
//
// "Most recent verdict" sidesteps that entirely: GET /api/v1/analysis/
// history already returns newest-first (see backend/services/
// analysis.py's _SQL_LOAD_HISTORY_PAGE), so the first item with a
// non-null verdict on the FIRST page is genuinely the account's latest
// decision, not an approximation -- which is why DashboardPage.tsx only
// renders this row when offset === 0 (see that file for the reasoning).

import { type HistoryEntryResponse, type Verdict } from "@/types/analysis";

export interface MostRecentDecidedVerdict {
  companyName: string;
  verdict: Verdict;
}

export interface DashboardKpis {
  /** GET /api/v1/analysis/history's total_count -- exact and page-independent. */
  totalAnalyses: number;
  /** Count of `items` (this page only) whose status is "completed". */
  completedOnPage: number;
  /** The newest item on this page that has a verdict, or null if none does. */
  mostRecentDecided: MostRecentDecidedVerdict | null;
}

/** Builds the Dashboard's KPI tile data from one page of analysis history. */
export function buildDashboardKpis(
  items: HistoryEntryResponse[],
  totalCount: number,
): DashboardKpis {
  const completedOnPage = items.filter((item) => item.status === "completed").length;
  const decidedItem = items.find((item) => item.verdict !== null);
  const mostRecentDecided =
    decidedItem && decidedItem.verdict
      ? { companyName: decidedItem.company_name, verdict: decidedItem.verdict }
      : null;

  return { totalAnalyses: totalCount, completedOnPage, mostRecentDecided };
}
