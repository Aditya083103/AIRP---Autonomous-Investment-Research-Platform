// frontend/src/test/SentimentGaugeChart.test.tsx
// Tests for SentimentGaugeChart (T-062). The centre score/label and
// the positive/neutral/negative article counts are plain JSX text
// overlaid on the gauge (not Recharts-owned), so they're asserted on
// directly; see StockPriceChart.test.tsx's docstring for the general
// jsdom/Recharts testing approach.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SentimentGaugeChart } from "@/components/charts/SentimentGaugeChart";
import { type SentimentChartResponse } from "@/types/analysis";

const SAMPLE_SENTIMENT: SentimentChartResponse = {
  sentiment_score: 0.42,
  sentiment_label: "positive",
  articles_analysed: 24,
  positive_articles: 14,
  negative_articles: 3,
  neutral_articles: 7,
};

describe("SentimentGaugeChart", () => {
  it("renders the chart title", () => {
    render(<SentimentGaugeChart sentiment={SAMPLE_SENTIMENT} />);
    expect(screen.getByText("News sentiment")).toBeInTheDocument();
  });

  it("renders the numeric sentiment score", () => {
    render(<SentimentGaugeChart sentiment={SAMPLE_SENTIMENT} />);
    expect(screen.getByText("0.42")).toBeInTheDocument();
  });

  it("renders a title-cased sentiment label", () => {
    render(<SentimentGaugeChart sentiment={SAMPLE_SENTIMENT} />);
    expect(screen.getByTestId("sentiment-gauge-label")).toHaveTextContent("Positive");
  });

  it("title-cases a multi-word label", () => {
    render(
      <SentimentGaugeChart sentiment={{ ...SAMPLE_SENTIMENT, sentiment_label: "very_positive" }} />,
    );
    expect(screen.getByTestId("sentiment-gauge-label")).toHaveTextContent("Very Positive");
  });

  it("renders the positive/neutral/negative article counts", () => {
    render(<SentimentGaugeChart sentiment={SAMPLE_SENTIMENT} />);
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows a fallback message when sentiment is null", () => {
    render(<SentimentGaugeChart sentiment={null} />);
    expect(
      screen.getByText("Sentiment data was not available for this analysis."),
    ).toBeInTheDocument();
  });
});
