// frontend/src/test/ConvictionGauge.test.tsx
// Tests for ConvictionGauge (T-061): the gauge clamps out-of-range
// scores, labels itself accessibly, picks the right verdict colour,
// and carries a CSS transition class on its animated arc so a change
// in score/verdict is visually animated rather than snapping instantly.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConvictionGauge } from "@/components/results/ConvictionGauge";

describe("ConvictionGauge", () => {
  it("renders an accessible label with the given score", () => {
    render(<ConvictionGauge score={8} verdict="BUY" />);
    expect(screen.getByRole("img", { name: "Conviction score 8 out of 10" })).toBeInTheDocument();
  });

  it("displays the numeric score in the gauge", () => {
    render(<ConvictionGauge score={7} verdict="HOLD" />);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("clamps scores above 10 down to 10", () => {
    render(<ConvictionGauge score={15} verdict="BUY" />);
    expect(screen.getByRole("img", { name: "Conviction score 10 out of 10" })).toBeInTheDocument();
  });

  it("clamps scores below 1 up to 1", () => {
    render(<ConvictionGauge score={0} verdict="SELL" />);
    expect(screen.getByRole("img", { name: "Conviction score 1 out of 10" })).toBeInTheDocument();
  });

  it("uses the buy colour for a BUY verdict", () => {
    render(<ConvictionGauge score={8} verdict="BUY" />);
    expect(screen.getByTestId("conviction-gauge-fill")).toHaveClass("stroke-verdict-buy");
  });

  it("uses the hold colour for a HOLD verdict", () => {
    render(<ConvictionGauge score={5} verdict="HOLD" />);
    expect(screen.getByTestId("conviction-gauge-fill")).toHaveClass("stroke-verdict-hold");
  });

  it("uses the sell colour for a SELL verdict", () => {
    render(<ConvictionGauge score={2} verdict="SELL" />);
    expect(screen.getByTestId("conviction-gauge-fill")).toHaveClass("stroke-verdict-sell");
  });

  it("animates the fill arc via a stroke-dashoffset transition", () => {
    render(<ConvictionGauge score={8} verdict="BUY" />);
    expect(screen.getByTestId("conviction-gauge-fill")).toHaveClass(
      "transition-[stroke-dashoffset]",
    );
  });

  it("fills more of the arc for a higher score", () => {
    const { unmount } = render(<ConvictionGauge score={2} verdict="SELL" />);
    const lowOffset = Number(
      screen.getByTestId("conviction-gauge-fill").getAttribute("stroke-dashoffset"),
    );
    unmount();

    render(<ConvictionGauge score={9} verdict="BUY" />);
    const highOffset = Number(
      screen.getByTestId("conviction-gauge-fill").getAttribute("stroke-dashoffset"),
    );

    // A higher score fills more of the arc, which means a SMALLER
    // remaining dashoffset (dashoffset counts down from the full arc
    // length toward 0 as more of the stroke is drawn).
    expect(highOffset).toBeLessThan(lowOffset);
  });
});
