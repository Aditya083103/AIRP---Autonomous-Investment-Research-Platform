// frontend/src/components/charts/ChartsPanel.tsx
// AIRP -- Charts & Visualisations panel (T-062)
//
// The T-062 deliverable: composes all 5 chart types into one
// responsive grid -- price history and revenue/profit trend get a full
// row each (they read best wide), while valuation, sentiment, and risk
// share a 3-column row on desktop that collapses to a single stacked
// column on mobile. Rendered by AnalysisResultPage once the live event
// stream reports the pipeline finished successfully, alongside
// <ResultsPanel> -- see that page's docstring for the fetch-gating
// rationale, identical here.
//
// Every chart component already renders its own "data not available"
// fallback when its slice of AnalysisChartDataResponse is null/empty
// (see each chart's own docstring) -- this panel's only extra
// responsibility is surfacing data_warnings, if any, once above all
// five charts so the person understands why a chart might be missing
// before they reach it.

import { PeerValuationChart } from "@/components/charts/PeerValuationChart";
import { RevenueProfitChart } from "@/components/charts/RevenueProfitChart";
import { RiskRadarChart } from "@/components/charts/RiskRadarChart";
import { SentimentGaugeChart } from "@/components/charts/SentimentGaugeChart";
import { StockPriceChart } from "@/components/charts/StockPriceChart";
import { type AnalysisChartDataResponse } from "@/types/analysis";

export interface ChartsPanelProps {
  data: AnalysisChartDataResponse;
}

/** Renders all 5 T-062 charts: price, revenue/profit, peer valuation, sentiment, risk. */
export function ChartsPanel({ data }: ChartsPanelProps): JSX.Element {
  return (
    <div className="space-y-4" data-testid="charts-panel">
      {data.data_warnings.length > 0 ? (
        <div
          className="rounded-card border border-verdict-hold/30 bg-verdict-hold/5 px-4 py-3 text-xs text-ink"
          data-testid="charts-panel-warnings"
        >
          <p className="font-semibold">Some charts could not be fully populated:</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {data.data_warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <StockPriceChart
        ticker={data.ticker}
        currency={data.price_currency}
        pricePoints={data.price_history}
      />

      <RevenueProfitChart financials={data.financials} />

      <div className="grid gap-4 md:grid-cols-3">
        <PeerValuationChart valuation={data.valuation} />
        <SentimentGaugeChart sentiment={data.sentiment} />
        <RiskRadarChart risk={data.risk} />
      </div>
    </div>
  );
}
