// frontend/src/components/charts/SentimentGaugeChart.tsx
// AIRP -- Sentiment score gauge (T-062)
//
// SentimentChartResponse.sentiment_score ranges -1.0 (very negative) to
// +1.0 (very positive) -- Recharts' RadialBarChart works in a single
// non-negative domain, so this component normalises the score to 0-100
// (0 = -1.0, 50 = neutral, 100 = +1.0) purely for the chart's own
// internal scale; the actual -1.0..+1.0 score is what's displayed as
// the centre label and in the surrounding article-count breakdown.

import { RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type SentimentChartResponse } from "@/types/analysis";

export interface SentimentGaugeChartProps {
  sentiment: SentimentChartResponse | null;
}

function colourForLabel(label: string): string {
  if (label.includes("positive")) {
    return CHART_COLORS.buy;
  }
  if (label.includes("negative")) {
    return CHART_COLORS.sell;
  }
  return CHART_COLORS.hold;
}

function formatLabel(label: string): string {
  return label
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Renders the News Sentiment agent's -1.0 to +1.0 score as a radial gauge. */
export function SentimentGaugeChart({ sentiment }: SentimentGaugeChartProps): JSX.Element {
  if (sentiment === null) {
    return (
      <Card data-testid="sentiment-gauge-chart">
        <Card.Header>
          <Card.Title>News sentiment</Card.Title>
        </Card.Header>
        <p className="text-sm text-muted">Sentiment data was not available for this analysis.</p>
      </Card>
    );
  }

  const normalisedValue = ((sentiment.sentiment_score + 1) / 2) * 100;
  const gaugeColour = colourForLabel(sentiment.sentiment_label);
  const chartData = [{ name: "sentiment", value: normalisedValue }];

  return (
    <Card data-testid="sentiment-gauge-chart">
      <Card.Header>
        <Card.Title>News sentiment</Card.Title>
      </Card.Header>
      <div className="relative">
        <ResponsiveContainer width="100%" height={200}>
          <RadialBarChart
            data={chartData}
            innerRadius="70%"
            outerRadius="100%"
            startAngle={180}
            endAngle={0}
            barSize={18}
          >
            <RadialBar
              dataKey="value"
              cornerRadius={9}
              fill={gaugeColour}
              background={{ fill: CHART_COLORS.line }}
              isAnimationActive
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-x-0 top-[58%] flex flex-col items-center">
          <span className="font-display text-2xl font-semibold text-ink">
            {sentiment.sentiment_score.toFixed(2)}
          </span>
          <span
            className="font-mono text-xs uppercase tracking-wide text-muted"
            data-testid="sentiment-gauge-label"
          >
            {formatLabel(sentiment.sentiment_label)}
          </span>
        </div>
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        <div>
          <dt className="text-muted">Positive</dt>
          <dd className="font-semibold text-verdict-buy">{sentiment.positive_articles}</dd>
        </div>
        <div>
          <dt className="text-muted">Neutral</dt>
          <dd className="font-semibold text-ink">{sentiment.neutral_articles}</dd>
        </div>
        <div>
          <dt className="text-muted">Negative</dt>
          <dd className="font-semibold text-verdict-sell">{sentiment.negative_articles}</dd>
        </div>
      </dl>
    </Card>
  );
}
