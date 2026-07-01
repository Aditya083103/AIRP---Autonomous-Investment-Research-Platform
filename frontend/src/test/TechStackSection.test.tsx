// frontend/src/test/TechStackSection.test.tsx
// Tests for TechStackSection (T-055): every listed technology renders as
// a chip, and there is no <img> in the section -- this section uses text
// wordmarks, never fetched brand-logo image assets.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TechStackSection } from "@/components/landing/TechStackSection";

describe("TechStackSection", () => {
  it("renders the built-with heading", () => {
    render(<TechStackSection />);
    expect(screen.getByText(/built with/i)).toBeInTheDocument();
  });

  it("renders a chip for each technology", () => {
    render(<TechStackSection />);
    for (const tech of ["React 18", "FastAPI", "LangGraph", "PostgreSQL", "Groq Llama 3.3"]) {
      expect(screen.getByText(tech)).toBeInTheDocument();
    }
  });

  it("uses no image logos", () => {
    const { container } = render(<TechStackSection />);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });
});
