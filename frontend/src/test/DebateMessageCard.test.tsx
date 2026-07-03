// frontend/src/test/DebateMessageCard.test.tsx
// Tests for DebateMessageCard (T-060). Takes a single DebateTranscriptMessage
// as a plain prop, so no stream/WebSocket mocking is required.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DebateMessageCard } from "@/components/debate/DebateMessageCard";
import { type DebateTranscriptMessage } from "@/lib/debateTranscript";

function makeMessage(overrides: Partial<DebateTranscriptMessage> = {}): DebateTranscriptMessage {
  return {
    id: "1-fundamental_analyst",
    nodeName: "fundamental_analyst",
    displayName: "Fundamental Analyst",
    seat: 1,
    round: 1,
    status: "completed",
    content: "Revenue grew 8% YoY with expanding margins.",
    turn: 1,
    ...overrides,
  };
}

describe("DebateMessageCard", () => {
  it("renders the agent's display name, seat, and status", () => {
    render(<DebateMessageCard message={makeMessage()} />);

    expect(screen.getByText("Fundamental Analyst")).toBeInTheDocument();
    expect(screen.getByText("Seat 1")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("assigns a distinct border colour per agent", () => {
    const { unmount } = render(<DebateMessageCard message={makeMessage()} />);
    const fundamentalCard = document.querySelector(
      '[data-agent="fundamental_analyst"]',
    ) as HTMLElement;
    const fundamentalColor = fundamentalCard.style.borderLeftColor;
    expect(fundamentalColor).not.toBe("");
    unmount();

    render(
      <DebateMessageCard
        message={makeMessage({
          nodeName: "risk_officer",
          displayName: "Risk Officer",
          seat: 5,
          round: 2,
        })}
      />,
    );
    const riskCard = document.querySelector('[data-agent="risk_officer"]') as HTMLElement;
    expect(riskCard.style.borderLeftColor).not.toBe("");
    expect(riskCard.style.borderLeftColor).not.toBe(fundamentalColor);
  });

  it("does not show an expand toggle for short messages", () => {
    render(<DebateMessageCard message={makeMessage({ content: "Short and sweet." })} />);
    expect(screen.queryByRole("button", { name: /show more/i })).not.toBeInTheDocument();
  });

  it("collapses long messages by default and expands on click", async () => {
    const longContent = "A".repeat(200);
    render(<DebateMessageCard message={makeMessage({ content: longContent })} />);

    const toggle = screen.getByRole("button", { name: /show more/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/A+…$/)).toBeInTheDocument();

    await userEvent.click(toggle);

    expect(screen.getByRole("button", { name: /show less/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText(longContent)).toBeInTheDocument();
  });
});
