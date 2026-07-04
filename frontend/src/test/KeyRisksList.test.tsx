// frontend/src/test/KeyRisksList.test.tsx
// Tests for KeyRisksList (T-061): risk summary, structured risks and
// catalysts render, and empty lists show an honest fallback rather
// than a blank section.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KeyRisksList } from "@/components/results/KeyRisksList";

describe("KeyRisksList", () => {
  it("renders the risk summary text", () => {
    render(
      <KeyRisksList
        riskSummary="Client concentration is the primary risk."
        keyRisks={[]}
        keyCatalysts={[]}
      />,
    );
    expect(screen.getByText("Client concentration is the primary risk.")).toBeInTheDocument();
  });

  it("renders every structured risk as a list item", () => {
    render(
      <KeyRisksList
        riskSummary="Summary"
        keyRisks={["Client concentration in BFSI", "INR/USD volatility"]}
        keyCatalysts={[]}
      />,
    );
    expect(screen.getByText("Client concentration in BFSI")).toBeInTheDocument();
    expect(screen.getByText("INR/USD volatility")).toBeInTheDocument();
  });

  it("renders every structured catalyst as a list item", () => {
    render(
      <KeyRisksList
        riskSummary="Summary"
        keyRisks={[]}
        keyCatalysts={["Large deal pipeline", "Margin recovery"]}
      />,
    );
    expect(screen.getByText("Large deal pipeline")).toBeInTheDocument();
    expect(screen.getByText("Margin recovery")).toBeInTheDocument();
  });

  it("shows a fallback when there are no structured risks", () => {
    render(<KeyRisksList riskSummary="Summary" keyRisks={[]} keyCatalysts={[]} />);
    expect(screen.getByText("No structured risks were flagged.")).toBeInTheDocument();
  });

  it("shows a fallback when there are no catalysts", () => {
    render(<KeyRisksList riskSummary="Summary" keyRisks={[]} keyCatalysts={[]} />);
    expect(screen.getByText("No catalysts were identified.")).toBeInTheDocument();
  });
});
