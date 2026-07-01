// frontend/src/components/ui/Card.test.tsx
// Tests for Card (T-054): the compound-component API (Card.Header,
// Card.Title, Card.Description, Card.Footer) renders correctly together,
// and the noPadding escape hatch actually removes the default padding.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Card } from "@/components/ui/Card";

describe("Card", () => {
  it("renders header, title, description, and footer together", () => {
    render(
      <Card>
        <Card.Header>
          <Card.Title>Fundamental Analyst</Card.Title>
        </Card.Header>
        <Card.Description>Revenue growth accelerating.</Card.Description>
        <Card.Footer>
          <button type="button">View detail</button>
        </Card.Footer>
      </Card>,
    );

    expect(screen.getByText("Fundamental Analyst")).toBeInTheDocument();
    expect(screen.getByText("Revenue growth accelerating.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View detail" })).toBeInTheDocument();
  });

  it("applies default padding unless noPadding is set", () => {
    render(<Card data-testid="card">content</Card>);
    expect(screen.getByTestId("card")).toHaveClass("p-6");
  });

  it("omits padding when noPadding is set", () => {
    render(
      <Card data-testid="card" noPadding>
        content
      </Card>,
    );
    expect(screen.getByTestId("card")).not.toHaveClass("p-6");
  });
});
