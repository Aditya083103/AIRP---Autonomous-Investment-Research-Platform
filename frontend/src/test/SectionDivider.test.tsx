// frontend/src/test/SectionDivider.test.tsx
// Tests for SectionDivider (landing-page redesign): renders as a
// decorative, non-announced seam between sections.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectionDivider } from "@/components/landing/SectionDivider";

describe("SectionDivider", () => {
  it("renders", () => {
    render(<SectionDivider />);
    expect(screen.getByTestId("section-divider")).toBeInTheDocument();
  });

  it("is hidden from assistive technology (purely decorative)", () => {
    render(<SectionDivider />);
    expect(screen.getByTestId("section-divider")).toHaveAttribute("aria-hidden", "true");
  });
});
