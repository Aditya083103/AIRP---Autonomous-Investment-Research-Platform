// frontend/src/components/ui/Badge.test.tsx
// Tests for Badge (T-054): renders its label, and the verdict tones
// (buy/hold/sell) map to AIRP's semantic colour tokens rather than each
// other -- a regression here would mean a SELL verdict rendering green.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/Badge";

describe("Badge", () => {
  it("renders its children", () => {
    render(<Badge>BUY</Badge>);
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("applies the buy tone's background token", () => {
    render(<Badge tone="buy">BUY</Badge>);
    expect(screen.getByText("BUY")).toHaveClass("bg-verdict-buy");
  });

  it("applies the sell tone's background token", () => {
    render(<Badge tone="sell">SELL</Badge>);
    expect(screen.getByText("SELL")).toHaveClass("bg-verdict-sell");
  });

  it("applies the hold tone's background token", () => {
    render(<Badge tone="hold">HOLD</Badge>);
    expect(screen.getByText("HOLD")).toHaveClass("bg-verdict-hold");
  });

  it("defaults to the neutral tone", () => {
    render(<Badge>Default</Badge>);
    expect(screen.getByText("Default")).toHaveClass("bg-canvas");
  });
});
