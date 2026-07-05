// frontend/src/test/CollapsibleSection.test.tsx
// Tests for CollapsibleSection (T-063): default-open rendering, toggle
// behaviour on click, aria-expanded state, and the defaultOpen={false}
// override used by MemoPage's "Agent weighting" section.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CollapsibleSection } from "@/components/ui/CollapsibleSection";

describe("CollapsibleSection", () => {
  it("renders the title and, by default, the expanded content", () => {
    render(
      <CollapsibleSection title="Executive summary">
        <p>Some memo content.</p>
      </CollapsibleSection>,
    );

    expect(screen.getByText("Executive summary")).toBeInTheDocument();
    expect(screen.getByText("Some memo content.")).toBeVisible();
    expect(screen.getByRole("button", { name: /Executive summary/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("starts collapsed when defaultOpen is false", () => {
    render(
      <CollapsibleSection title="Agent weighting" defaultOpen={false}>
        <p>Weighting detail.</p>
      </CollapsibleSection>,
    );

    expect(screen.getByRole("button", { name: /Agent weighting/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByText("Weighting detail.")).not.toBeVisible();
  });

  it("toggles closed then open again when the header is clicked", async () => {
    const user = userEvent.setup();
    render(
      <CollapsibleSection title="Valuation">
        <p>Valuation detail.</p>
      </CollapsibleSection>,
    );

    const toggle = screen.getByRole("button", { name: /Valuation/ });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Valuation detail.")).not.toBeVisible();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Valuation detail.")).toBeVisible();
  });

  it("renders optional header extra content next to the title", () => {
    render(
      <CollapsibleSection title="Contrarian resolution" headerExtra={<span>2 rounds</span>}>
        <p>Resolution detail.</p>
      </CollapsibleSection>,
    );

    expect(screen.getByText("2 rounds")).toBeInTheDocument();
  });
});
