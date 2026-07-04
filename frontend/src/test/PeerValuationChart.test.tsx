// frontend/src/test/PeerValuationChart.test.tsx
// Tests for PeerValuationChart (T-062). See StockPriceChart.test.tsx's
// docstring for the jsdom/Recharts testing approach; the peer-tickers
// caption is plain JSX text (not Recharts-owned) so it's asserted on
// directly.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PeerValuationChart } from "@/components/charts/PeerValuationChart";
import { type ValuationChartResponse } from "@/types/analysis";

const SAMPLE_VALUATION: ValuationChartResponse = {
  pe_ratio: 28.4,
  sector_avg_pe: 24.1,
  pb_ratio: 11.2,
  sector_avg_pb: 9.8,
  ev_ebitda: 19.6,
  sector_avg_ev_ebitda: 17.3,
  peer_tickers: ["INFY.NS", "WIPRO.NS"],
};

describe("PeerValuationChart", () => {
  it("renders the chart title", () => {
    render(<PeerValuationChart valuation={SAMPLE_VALUATION} />);
    expect(screen.getByText("Valuation vs peers")).toBeInTheDocument();
  });

  it("renders the chart container when valuation data is present", () => {
    render(<PeerValuationChart valuation={SAMPLE_VALUATION} />);
    expect(screen.getByTestId("peer-valuation-chart")).toBeInTheDocument();
  });

  it("lists the peer tickers used in the comparison", () => {
    render(<PeerValuationChart valuation={SAMPLE_VALUATION} />);
    expect(screen.getByText("Peers: INFY.NS, WIPRO.NS")).toBeInTheDocument();
  });

  it("shows a fallback message when valuation is null", () => {
    render(<PeerValuationChart valuation={null} />);
    expect(
      screen.getByText("Peer valuation data was not available for this analysis."),
    ).toBeInTheDocument();
  });

  it("shows a fallback message when every metric is null", () => {
    render(
      <PeerValuationChart
        valuation={{
          pe_ratio: null,
          sector_avg_pe: null,
          pb_ratio: null,
          sector_avg_pb: null,
          ev_ebitda: null,
          sector_avg_ev_ebitda: null,
          peer_tickers: [],
        }}
      />,
    );
    expect(
      screen.getByText("Peer valuation data was not available for this analysis."),
    ).toBeInTheDocument();
  });
});
