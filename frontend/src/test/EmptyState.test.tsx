// frontend/src/test/EmptyState.test.tsx
// Tests for EmptyState (T-066): renders the title always, description
// and action only when provided.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/ui/EmptyState";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState title="Nothing here yet." />);
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });

  it("renders a description when provided", () => {
    render(<EmptyState title="Nothing here yet." description="Come back later." />);
    expect(screen.getByText("Come back later.")).toBeInTheDocument();
  });

  it("omits the description when not provided", () => {
    render(<EmptyState title="Nothing here yet." />);
    expect(screen.queryByText("Come back later.")).not.toBeInTheDocument();
  });

  it("renders an action when provided", () => {
    render(<EmptyState title="Nothing here yet." action={<button type="button">Do it</button>} />);
    expect(screen.getByRole("button", { name: "Do it" })).toBeInTheDocument();
  });
});
