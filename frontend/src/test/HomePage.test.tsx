// frontend/src/test/HomePage.test.tsx
// Integration test for HomePage (T-055): confirms the full landing page
// composes without crashing and every section is present in the render
// tree -- a regression guard for the composition itself, since each
// section already has its own focused test file.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { HomePage } from "@/pages/HomePage";

describe("HomePage", () => {
  it("renders the hero, committee, how-it-works, CTA, stack, and footer sections", () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: /eight agents research, debate, and decide/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/eight specialists, one shared state/i)).toBeInTheDocument();
    expect(screen.getByText(/one request, five stages/i)).toBeInTheDocument();
    expect(screen.getByText(/pick an indian equity/i)).toBeInTheDocument();
    expect(screen.getByText(/built with/i)).toBeInTheDocument();
    expect(screen.getByText(/not investment advice/i)).toBeInTheDocument();
  });

  it("renders exactly one <h1>", () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
