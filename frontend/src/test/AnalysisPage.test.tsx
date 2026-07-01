// frontend/src/test/AnalysisPage.test.tsx
// Tests for AnalysisPage (T-055): the placeholder renders honest "coming
// soon" copy (never a fake working form) and its link back navigates to
// the landing page's how-it-works anchor.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AnalysisPage } from "@/pages/AnalysisPage";

describe("AnalysisPage", () => {
  it("renders a coming-soon heading", () => {
    render(
      <MemoryRouter>
        <AnalysisPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: /analysis input page is being built/i }),
    ).toBeInTheDocument();
  });

  it("links back to the how-it-works section", () => {
    render(
      <MemoryRouter>
        <AnalysisPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /see how it works/i })).toHaveAttribute(
      "href",
      "/#how-it-works",
    );
  });
});
