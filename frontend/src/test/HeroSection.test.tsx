// frontend/src/test/HeroSection.test.tsx
// Tests for HeroSection (T-055): the headline renders, the primary CTA
// links to /analysis, the secondary CTA anchors to #how-it-works, and the
// example-output card is clearly labelled as an example (never a live or
// real recommendation).

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { HeroSection } from "@/components/landing/HeroSection";

describe("HeroSection", () => {
  it("renders the headline", () => {
    render(
      <MemoryRouter>
        <HeroSection />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /eight agents research, debate, and decide/i,
      }),
    ).toBeInTheDocument();
  });

  it("links the primary CTA to the analysis page", () => {
    render(
      <MemoryRouter>
        <HeroSection />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /run a live analysis/i })).toHaveAttribute(
      "href",
      "/analysis",
    );
  });

  it("links the secondary CTA to the how-it-works anchor", () => {
    render(
      <MemoryRouter>
        <HeroSection />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /see how it works/i })).toHaveAttribute(
      "href",
      "#how-it-works",
    );
  });

  it("labels the preview card as an example, not a live result", () => {
    render(
      <MemoryRouter>
        <HeroSection />
      </MemoryRouter>,
    );
    expect(screen.getByText(/example output/i)).toBeInTheDocument();
  });
});
