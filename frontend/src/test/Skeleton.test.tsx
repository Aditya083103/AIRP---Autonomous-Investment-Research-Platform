// frontend/src/test/Skeleton.test.tsx
// Tests for Skeleton (T-066): a purely decorative placeholder bar --
// every instance is aria-hidden (see the component's own docstring on
// why the *composition* around it, not the bar itself, carries the
// accessible loading announcement).

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Skeleton } from "@/components/ui/Skeleton";

describe("Skeleton", () => {
  it("renders as aria-hidden", () => {
    const { container } = render(<Skeleton data-testid="bar" />);
    expect(container.querySelector('[data-testid="bar"]')).toHaveAttribute("aria-hidden", "true");
  });

  it("applies caller-provided sizing classes", () => {
    const { container } = render(<Skeleton data-testid="bar" className="h-4 w-32" />);
    const bar = container.querySelector('[data-testid="bar"]');
    expect(bar?.className).toContain("h-4");
    expect(bar?.className).toContain("w-32");
  });
});
