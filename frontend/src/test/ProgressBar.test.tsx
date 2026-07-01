// frontend/src/components/ui/ProgressBar.test.tsx
// Tests for ProgressBar (T-054): the ARIA progressbar attributes reflect
// the given value, out-of-range values are clamped to [0, 100] rather
// than producing an invalid or visually broken bar, and the label/percent
// text render when requested.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar } from "@/components/ui/ProgressBar";

describe("ProgressBar", () => {
  it("sets aria-valuenow to the given value", () => {
    render(<ProgressBar value={42} label="Fundamental Analyst" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  });

  it("clamps values above 100 down to 100", () => {
    render(<ProgressBar value={150} label="Over" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("clamps negative values up to 0", () => {
    render(<ProgressBar value={-20} label="Under" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("renders the label text", () => {
    render(<ProgressBar value={50} label="Technical Analyst" />);
    expect(screen.getByText("Technical Analyst")).toBeInTheDocument();
  });

  it("renders the rounded percentage when showValue is true", () => {
    render(<ProgressBar value={67.8} label="News Sentiment" />);
    expect(screen.getByText("68%")).toBeInTheDocument();
  });

  it("does not render the percentage when showValue is false", () => {
    render(<ProgressBar value={50} label="Macro Economist" showValue={false} />);
    expect(screen.queryByText("50%")).not.toBeInTheDocument();
  });
});
