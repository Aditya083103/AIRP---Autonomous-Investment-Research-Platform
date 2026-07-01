// frontend/src/test/HowItWorksSection.test.tsx
// Tests for HowItWorksSection (T-055): the 5 steps render, numbered
// 01-05, in document order (an ordered <ol> so screen readers announce
// position, e.g. "item 3 of 5").

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HowItWorksSection } from "@/components/landing/HowItWorksSection";

describe("HowItWorksSection", () => {
  it("renders all 5 steps as an ordered list", () => {
    render(<HowItWorksSection />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
  });

  it("numbers the steps 01 through 05 in order", () => {
    render(<HowItWorksSection />);
    const numberEls = ["01", "02", "03", "04", "05"].map((n) => screen.getByText(n));
    for (let i = 1; i < numberEls.length; i += 1) {
      const previous = numberEls[i - 1] as HTMLElement;
      const current = numberEls[i] as HTMLElement;
      expect(previous.compareDocumentPosition(current) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(
        0,
      );
    }
  });

  it("renders the final step naming the Portfolio Manager's decision", () => {
    render(<HowItWorksSection />);
    expect(
      screen.getByRole("heading", { name: /the portfolio manager decides/i }),
    ).toBeInTheDocument();
  });
});
