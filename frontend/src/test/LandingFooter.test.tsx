// frontend/src/test/LandingFooter.test.tsx
// Tests for LandingFooter (T-055): the GitHub link is a real external
// link opened safely (target + rel), internal links stay same-tab, and
// the investment-advice disclaimer is present and unambiguous.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { LandingFooter } from "@/components/landing/LandingFooter";

describe("LandingFooter", () => {
  it("opens the GitHub link safely in a new tab", () => {
    render(
      <MemoryRouter>
        <LandingFooter />
      </MemoryRouter>,
    );
    const githubLink = screen.getByRole("link", { name: /source on github/i });
    expect(githubLink).toHaveAttribute("target", "_blank");
    expect(githubLink).toHaveAttribute("rel", "noreferrer");
  });

  it("does not open internal links in a new tab", () => {
    render(
      <MemoryRouter>
        <LandingFooter />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /how it works/i })).not.toHaveAttribute("target");
  });

  it("shows the not-investment-advice disclaimer", () => {
    render(
      <MemoryRouter>
        <LandingFooter />
      </MemoryRouter>,
    );
    expect(screen.getByText(/not investment advice/i)).toBeInTheDocument();
  });
});
