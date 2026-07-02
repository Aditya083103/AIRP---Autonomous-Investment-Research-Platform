// frontend/src/test/HistoryTable.test.tsx
// Tests for HistoryTable (T-057): renders company/ticker, a formatted
// conviction score (or an em dash when null), and a working detail link
// per row.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { HistoryTable } from "@/components/dashboard/HistoryTable";
import { type HistoryEntryResponse } from "@/types/analysis";

const ENTRIES: HistoryEntryResponse[] = [
  {
    job_id: "11111111-1111-1111-1111-111111111111",
    company_name: "Infosys",
    ticker: "INFY.NS",
    exchange: "NSE",
    status: "completed",
    requested_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:01:00Z",
    verdict: "BUY",
    conviction_score: 8,
  },
  {
    job_id: "22222222-2222-2222-2222-222222222222",
    company_name: "Tata Consultancy Services",
    ticker: "TCS.NS",
    exchange: "NSE",
    status: "pending",
    requested_at: "2026-01-02T00:00:00Z",
    completed_at: null,
    verdict: null,
    conviction_score: null,
  },
];

function renderTable(entries: HistoryEntryResponse[] = ENTRIES): void {
  render(
    <MemoryRouter>
      <HistoryTable entries={entries} />
    </MemoryRouter>,
  );
}

describe("HistoryTable", () => {
  it("renders a row per entry with company name and ticker", () => {
    renderTable();
    expect(screen.getByText("Infosys")).toBeInTheDocument();
    expect(screen.getByText("INFY.NS")).toBeInTheDocument();
    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
  });

  it("formats a present conviction score as X/10", () => {
    renderTable();
    expect(screen.getByText("8/10")).toBeInTheDocument();
  });

  it("shows an em dash when the conviction score is not yet available", () => {
    renderTable();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("links each row to its result detail page", () => {
    renderTable();
    const links = screen.getAllByRole("link", { name: "View" });
    expect(links[0]).toHaveAttribute(
      "href",
      "/analysis/11111111-1111-1111-1111-111111111111/result",
    );
  });
});
