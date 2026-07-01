// frontend/src/test/DemoCtaSection.test.tsx
// Tests for DemoCtaSection (T-055): the CTA band renders its heading and
// its button links to /analysis, matching the hero's primary CTA target.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DemoCtaSection } from "@/components/landing/DemoCtaSection";

describe("DemoCtaSection", () => {
  it("renders its heading", () => {
    render(
      <MemoryRouter>
        <DemoCtaSection />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /pick an indian equity/i })).toBeInTheDocument();
  });

  it("links the CTA to the analysis page", () => {
    render(
      <MemoryRouter>
        <DemoCtaSection />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /start a free analysis/i })).toHaveAttribute(
      "href",
      "/analysis",
    );
  });
});
