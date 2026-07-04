// frontend/src/test/BullBearPanel.test.tsx
// Tests for BullBearPanel (T-061): both cases render, and an empty
// case shows an honest fallback rather than a blank card.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BullBearPanel } from "@/components/results/BullBearPanel";

describe("BullBearPanel", () => {
  it("renders both the bull case and bear case headings", () => {
    render(<BullBearPanel bullCase="Strong revenue growth." bearCase="Rich valuation." />);
    expect(screen.getByText("Bull case")).toBeInTheDocument();
    expect(screen.getByText("Bear case")).toBeInTheDocument();
  });

  it("renders the bull case text", () => {
    render(<BullBearPanel bullCase="Strong revenue growth." bearCase="Rich valuation." />);
    expect(screen.getByText("Strong revenue growth.")).toBeInTheDocument();
  });

  it("renders the bear case text", () => {
    render(<BullBearPanel bullCase="Strong revenue growth." bearCase="Rich valuation." />);
    expect(screen.getByText("Rich valuation.")).toBeInTheDocument();
  });

  it("shows a fallback message when the bull case is empty", () => {
    render(<BullBearPanel bullCase="" bearCase="Rich valuation." />);
    expect(screen.getByText("No bull case was recorded for this analysis.")).toBeInTheDocument();
  });

  it("shows a fallback message when the bear case is empty", () => {
    render(<BullBearPanel bullCase="Strong revenue growth." bearCase="" />);
    expect(screen.getByText("No bear case was recorded for this analysis.")).toBeInTheDocument();
  });

  it("lays the two cases out in a responsive two-column grid", () => {
    render(<BullBearPanel bullCase="Bull text" bearCase="Bear text" />);
    expect(screen.getByTestId("bull-bear-panel")).toHaveClass("md:grid-cols-2");
  });
});
