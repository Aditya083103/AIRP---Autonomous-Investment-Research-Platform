// frontend/src/test/CommitteeSection.test.tsx
// Tests for CommitteeSection (T-055): all 8 agents render with their
// seat number, and the three round headings (parallel research, debate,
// final call) are present -- guards against an agent silently dropping
// off the committee during a future edit.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CommitteeSection } from "@/components/landing/CommitteeSection";

const AGENT_NAMES = [
  "Fundamental Analyst",
  "Technical Analyst",
  "News Sentiment Agent",
  "Macro Economist",
  "Risk Officer",
  "Contrarian Investor",
  "Valuation Agent",
  "Portfolio Manager",
];

describe("CommitteeSection", () => {
  it("renders all 8 committee agents", () => {
    render(<CommitteeSection />);
    for (const name of AGENT_NAMES) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  });

  it("renders the three execution rounds", () => {
    render(<CommitteeSection />);
    expect(screen.getByText(/round 1.*parallel research/i)).toBeInTheDocument();
    expect(screen.getByText(/round 2.*debate/i)).toBeInTheDocument();
    expect(screen.getByText(/final call/i)).toBeInTheDocument();
  });

  it("gives each agent card its seat number", () => {
    render(<CommitteeSection />);
    expect(screen.getByText("Seat 1")).toBeInTheDocument();
    expect(screen.getByText("Seat 8")).toBeInTheDocument();
  });
});
