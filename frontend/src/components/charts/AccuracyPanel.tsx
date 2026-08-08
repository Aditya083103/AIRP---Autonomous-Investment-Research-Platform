// frontend/src/components/charts/AccuracyPanel.tsx
// AIRP -- Accuracy dashboard panel (T-092)
//
// The T-092 deliverable's chart composition: the AccuracySummaryStats
// overview row, then the rolling accuracy trend line (full width, reads
// best wide -- the same layout call StockPriceChart/RevenueProfitChart
// get on AnalysisResultPage's ChartsPanel), then the verdict-type bar
// chart and the conviction-vs-outcome scatter side by side on desktop,
// stacked on mobile -- mirrors ChartsPanel's own `md:grid-cols-3`
// breakpoint choice (this row only has 2 charts, not 3, so
// `md:grid-cols-2`) for "the point at which this app treats mobile vs
// desktop" consistency across every Phase 6+ chart layout.
//
// Takes the summary and history responses as two separate, already-
// resolved props rather than fetching them itself -- AccuracyPage owns
// the two useQuery calls and their independent loading/error states
// (see that file's docstring for why summary and history are kept as
// two separate queries), so this component's only job is composition,
// the same "dumb panel, smart page" split ChartsPanel/AnalysisResultPage
// already establish.

import { AccuracySummaryStats } from "@/components/charts/AccuracySummaryStats";
import { AccuracyTrendChart } from "@/components/charts/AccuracyTrendChart";
import { ConvictionAccuracyScatterChart } from "@/components/charts/ConvictionAccuracyScatterChart";
import { VerdictAccuracyChart } from "@/components/charts/VerdictAccuracyChart";
import { type AccuracyHistoryEntryResponse, type AccuracySummaryResponse } from "@/types/accuracy";

export interface AccuracyPanelProps {
  summary: AccuracySummaryResponse;
  historyEntries: AccuracyHistoryEntryResponse[];
}

/** Renders the T-092 accuracy dashboard: summary stats, trend line, verdict bars, scatter. */
export function AccuracyPanel({ summary, historyEntries }: AccuracyPanelProps): JSX.Element {
  return (
    <div className="space-y-4" data-testid="accuracy-panel">
      <AccuracySummaryStats summary={summary} />

      <AccuracyTrendChart entries={historyEntries} />

      <div className="grid gap-4 md:grid-cols-2">
        <VerdictAccuracyChart byVerdict={summary.by_verdict} />
        <ConvictionAccuracyScatterChart entries={historyEntries} />
      </div>
    </div>
  );
}
