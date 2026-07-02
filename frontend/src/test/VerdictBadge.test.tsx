// frontend/src/test/VerdictBadge.test.tsx
// Tests for VerdictBadge (T-057): each real verdict renders its matching
// Badge tone, and the no-verdict-yet cases (pending/running/failed) each
// render something sensible instead of a blank cell.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerdictBadge } from "@/components/dashboard/VerdictBadge";

describe("VerdictBadge", () => {
  it("renders BUY", () => {
    render(<VerdictBadge verdict="BUY" status="completed" />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("renders HOLD", () => {
    render(<VerdictBadge verdict="HOLD" status="completed" />);
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });

  it("renders SELL", () => {
    render(<VerdictBadge verdict="SELL" status="completed" />);
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });

  it("renders Pending for a pending analysis with no verdict yet", () => {
    render(<VerdictBadge verdict={null} status="pending" />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("renders Running for a running analysis", () => {
    render(<VerdictBadge verdict={null} status="running" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("renders Failed for a failed analysis", () => {
    render(<VerdictBadge verdict={null} status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});
