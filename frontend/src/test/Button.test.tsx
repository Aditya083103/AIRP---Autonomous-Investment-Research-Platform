// frontend/src/components/ui/Button.test.tsx
// Tests for Button (T-054): every variant renders its label, clicking
// calls the provided handler, and both `disabled` and `isLoading` block
// further clicks (isLoading also sets aria-busy for screen readers).

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/Button";

describe("Button", () => {
  it("renders its children as the visible label", () => {
    render(<Button>Run analysis</Button>);
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeInTheDocument();
  });

  it("calls onClick when clicked", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={handleClick}>Click me</Button>);

    await user.click(screen.getByRole("button", { name: "Click me" }));

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("does not call onClick when disabled", async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button onClick={handleClick} disabled>
        Disabled
      </Button>,
    );

    await user.click(screen.getByRole("button", { name: "Disabled" }));

    expect(handleClick).not.toHaveBeenCalled();
  });

  it("is disabled and marked aria-busy while isLoading", () => {
    render(<Button isLoading>Saving</Button>);
    const button = screen.getByRole("button", { name: /saving/i });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("stays disabled while isLoading even if disabled is explicitly false", () => {
    render(
      <Button isLoading disabled={false}>
        Saving
      </Button>,
    );
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });

  it.each(["primary", "secondary", "ghost", "danger"] as const)(
    "renders the %s variant without crashing",
    (variant) => {
      render(<Button variant={variant}>Action</Button>);
      expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
    },
  );
});
