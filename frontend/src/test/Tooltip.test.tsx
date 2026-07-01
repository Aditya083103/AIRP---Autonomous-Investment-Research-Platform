// frontend/src/components/ui/Tooltip.test.tsx
// Tests for Tooltip (T-054): the tooltip text exists in the DOM (always
// rendered, toggled via classes) but is visually hidden until hover or
// keyboard focus, and the trigger is linked to it via aria-describedby
// so screen readers announce the content regardless of visibility.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Tooltip } from "@/components/ui/Tooltip";

describe("Tooltip", () => {
  it("links the trigger to the tooltip via aria-describedby", () => {
    render(
      <Tooltip content="Conviction score explained">
        <button type="button">Info</button>
      </Tooltip>,
    );

    const trigger = screen.getByRole("button", { name: "Info" });
    const tooltip = screen.getByRole("tooltip");

    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
  });

  it("is hidden until the trigger is hovered", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Conviction score explained">
        <button type="button">Info</button>
      </Tooltip>,
    );

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveClass("invisible");

    await user.hover(screen.getByRole("button", { name: "Info" }));

    expect(tooltip).toHaveClass("visible");
  });

  it("is shown on keyboard focus and hidden again on blur", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Conviction score explained">
        <button type="button">Info</button>
      </Tooltip>,
    );

    const trigger = screen.getByRole("button", { name: "Info" });
    const tooltip = screen.getByRole("tooltip");

    await user.tab();
    expect(trigger).toHaveFocus();
    expect(tooltip).toHaveClass("visible");

    await user.tab();
    expect(tooltip).toHaveClass("invisible");
  });
});
