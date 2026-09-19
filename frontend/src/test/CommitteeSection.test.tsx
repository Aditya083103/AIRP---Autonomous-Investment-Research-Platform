// frontend/src/test/CommitteeSection.test.tsx
// Tests for CommitteeSection: all 8 agents render with their seat
// number, and the three round headings (parallel research, debate,
// final call) are present -- guards against an agent silently dropping
// off the committee during a future edit.
//
// Landing-page redesign: each round's ordinal now renders as its own
// Badge element next to a plain-text title (see CommitteeSection.tsx's
// own docstring), rather than one "Round N — Title" string -- asserted
// here as two separate getByText checks per round rather than one
// regex spanning both, since testing-library's getNodeText only reads
// an element's own direct text children, not a full recursive
// textContent, so a match spanning a nested Badge and its sibling text
// would never actually be found by a single query.

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
    expect(screen.getByText("Round 1")).toBeInTheDocument();
    expect(screen.getByText("Parallel research")).toBeInTheDocument();
    expect(screen.getByText("Round 2")).toBeInTheDocument();
    expect(screen.getByText(/debate & challenge/i)).toBeInTheDocument();
    expect(screen.getByText("Round 3")).toBeInTheDocument();
    expect(screen.getByText(/final call/i)).toBeInTheDocument();
  });

  it("gives each agent card its seat number", () => {
    render(<CommitteeSection />);
    expect(screen.getByText("Seat 1")).toBeInTheDocument();
    expect(screen.getByText("Seat 8")).toBeInTheDocument();
  });
});
