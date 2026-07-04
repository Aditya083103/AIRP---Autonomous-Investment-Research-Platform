// frontend/src/test/MemoSection.test.tsx
// Tests for MemoSection (T-061): title and content render, and the
// default/custom empty-state fallback shows when content is "".

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemoSection } from "@/components/results/MemoSection";

describe("MemoSection", () => {
  it("renders the given title", () => {
    render(<MemoSection title="Executive summary" content="Some content." />);
    expect(screen.getByText("Executive summary")).toBeInTheDocument();
  });

  it("renders the given content", () => {
    render(<MemoSection title="Executive summary" content="Some content." />);
    expect(screen.getByText("Some content.")).toBeInTheDocument();
  });

  it("shows the default empty-state message when content is empty", () => {
    render(<MemoSection title="Valuation" content="" />);
    expect(screen.getByText("Not available for this analysis.")).toBeInTheDocument();
  });

  it("shows a custom empty-state message when provided", () => {
    render(<MemoSection title="Contrarian resolution" content="" emptyLabel="Nothing recorded." />);
    expect(screen.getByText("Nothing recorded.")).toBeInTheDocument();
  });
});
