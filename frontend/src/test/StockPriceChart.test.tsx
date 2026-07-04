// frontend/src/test/StockPriceChart.test.tsx
// Tests for StockPriceChart (T-062). Recharts' ResponsiveContainer
// depends on layout (see test/setup.ts's ResizeObserver/
// getBoundingClientRect mocks) -- these tests focus on the chart's
// title, empty-state fallback, and top-level container, which render
// regardless of Recharts' own internal SVG output, rather than
// asserting on specific bar/line/tick DOM nodes Recharts owns.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StockPriceChart } from "@/components/charts/StockPriceChart";
import { type PricePointResponse } from "@/types/analysis";

const SAMPLE_POINTS: PricePointResponse[] = [
  { date: "2026-06-18", close: 3845.2, volume: 1_204_500 },
  { date: "2026-06-19", close: 3862.55, volume: 980_200 },
];

describe("StockPriceChart", () => {
  it("renders the ticker in the chart title", () => {
    render(<StockPriceChart ticker="TCS.NS" currency="INR" pricePoints={SAMPLE_POINTS} />);
    expect(screen.getByText("TCS.NS -- 1-year price")).toBeInTheDocument();
  });

  it("renders the chart container when price points are present", () => {
    render(<StockPriceChart ticker="TCS.NS" currency="INR" pricePoints={SAMPLE_POINTS} />);
    expect(screen.getByTestId("stock-price-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when price history is empty", () => {
    render(<StockPriceChart ticker="TCS.NS" currency="INR" pricePoints={[]} />);
    expect(
      screen.getByText("Price history was not available for this analysis."),
    ).toBeInTheDocument();
  });
});
