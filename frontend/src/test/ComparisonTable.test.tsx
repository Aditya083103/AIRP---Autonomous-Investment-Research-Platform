// frontend/src/test/ComparisonTable.test.tsx
// Tests for ComparisonTable (T-064). Feeds hand-built ComparisonRow[]
// fixtures directly -- no need to go through winnerLogic.ts here since
// that module has its own dedicated tests (winnerLogic.test.ts).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComparisonTable } from "@/components/compare/ComparisonTable";
import { type ComparisonRow } from "@/lib/compare/winnerLogic";

const ROWS: ComparisonRow[] = [
  { id: "verdict", label: "Verdict", displayA: "BUY", displayB: "SELL", winner: "a" },
  {
    id: "conviction_score",
    label: "Conviction score",
    displayA: "9/10",
    displayB: "4/10",
    winner: "a",
  },
  { id: "pe_ratio", label: "P/E ratio", displayA: "20.00", displayB: "20.00", winner: "tie" },
  { id: "risk_score", label: "Risk score", displayA: "--", displayB: "--", winner: null },
];

describe("ComparisonTable", () => {
  it("renders the table with both company names as column headers", () => {
    render(<ComparisonTable companyNameA="Infosys" companyNameB="TCS" rows={ROWS} />);

    expect(screen.getByTestId("comparison-table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Infosys" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "TCS" })).toBeInTheDocument();
  });

  it("renders every row's label and both display values", () => {
    render(<ComparisonTable companyNameA="Infosys" companyNameB="TCS" rows={ROWS} />);

    expect(screen.getByText("Verdict")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("Conviction score")).toBeInTheDocument();
  });

  it("shows a 'Winner' badge only in the winning cell", () => {
    render(<ComparisonTable companyNameA="Infosys" companyNameB="TCS" rows={ROWS} />);

    const verdictCellA = screen.getByTestId("cell-verdict-a");
    const verdictCellB = screen.getByTestId("cell-verdict-b");
    expect(verdictCellA).toHaveTextContent("Winner");
    expect(verdictCellB).not.toHaveTextContent("Winner");
  });

  it("shows no 'Winner' badge for a tied row", () => {
    render(<ComparisonTable companyNameA="Infosys" companyNameB="TCS" rows={ROWS} />);

    expect(screen.getByTestId("cell-pe_ratio-a")).not.toHaveTextContent("Winner");
    expect(screen.getByTestId("cell-pe_ratio-b")).not.toHaveTextContent("Winner");
  });

  it("shows no 'Winner' badge for a row with a null winner", () => {
    render(<ComparisonTable companyNameA="Infosys" companyNameB="TCS" rows={ROWS} />);

    expect(screen.getByTestId("cell-risk_score-a")).not.toHaveTextContent("Winner");
    expect(screen.getByTestId("cell-risk_score-b")).not.toHaveTextContent("Winner");
  });
});
