// frontend/src/components/charts/index.ts
// Barrel export for the T-062 charts & visualisations components, plus
// the T-092 accuracy dashboard charts.
// Mirrors the pattern already used by src/components/results/index.ts.

export { AccuracyPanel, type AccuracyPanelProps } from "@/components/charts/AccuracyPanel";
export {
  AccuracySummaryStats,
  type AccuracySummaryStatsProps,
} from "@/components/charts/AccuracySummaryStats";
export {
  AccuracyTrendChart,
  type AccuracyTrendChartProps,
} from "@/components/charts/AccuracyTrendChart";
export { ChartsPanel, type ChartsPanelProps } from "@/components/charts/ChartsPanel";
export {
  ConvictionAccuracyScatterChart,
  type ConvictionAccuracyScatterChartProps,
} from "@/components/charts/ConvictionAccuracyScatterChart";
export {
  PeerValuationChart,
  type PeerValuationChartProps,
} from "@/components/charts/PeerValuationChart";
export {
  RevenueProfitChart,
  type RevenueProfitChartProps,
} from "@/components/charts/RevenueProfitChart";
export { RiskRadarChart, type RiskRadarChartProps } from "@/components/charts/RiskRadarChart";
export {
  SentimentGaugeChart,
  type SentimentGaugeChartProps,
} from "@/components/charts/SentimentGaugeChart";
export { StockPriceChart, type StockPriceChartProps } from "@/components/charts/StockPriceChart";
export {
  VerdictAccuracyChart,
  type VerdictAccuracyChartProps,
} from "@/components/charts/VerdictAccuracyChart";
