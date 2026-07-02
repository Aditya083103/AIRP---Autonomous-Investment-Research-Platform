// frontend/src/test/TypingIndicator.test.tsx
// Tests for TypingIndicator (T-059): renders as an accessible status
// region (so a screen reader announces "Thinking" once, not three
// unlabelled dots), and renders exactly 3 dot elements.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TypingIndicator } from "@/components/progress/TypingIndicator";

describe("TypingIndicator", () => {
  it("exposes an accessible 'Thinking' status", () => {
    render(<TypingIndicator />);
    expect(screen.getByRole("status", { name: "Thinking" })).toBeInTheDocument();
  });

  it("renders exactly 3 dots", () => {
    const { container } = render(<TypingIndicator />);
    const dots = container.querySelectorAll("[class*='animate-bounce']");
    expect(dots).toHaveLength(3);
  });
});
