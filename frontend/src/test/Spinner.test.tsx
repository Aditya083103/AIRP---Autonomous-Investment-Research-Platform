// frontend/src/components/ui/Spinner.test.tsx
// Tests for Spinner (T-054): announces "Loading" via role="status" by
// default (screen readers need to know work is in progress), and goes
// fully silent -- no role, no sr-only text -- when aria-hidden is passed,
// which is how Button uses it to avoid double-announcing its own
// aria-busy state.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Spinner } from "@/components/ui/Spinner";

describe("Spinner", () => {
  it("announces a status role by default", () => {
    render(<Spinner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("uses a custom label when provided", () => {
    render(<Spinner label="Fetching results" />);
    expect(screen.getByText("Fetching results")).toBeInTheDocument();
  });

  it("renders no status role when aria-hidden is true", () => {
    render(<Spinner aria-hidden="true" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
