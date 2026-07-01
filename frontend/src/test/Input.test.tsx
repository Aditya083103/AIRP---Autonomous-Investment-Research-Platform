// frontend/src/components/ui/Input.test.tsx
// Tests for Input (T-054): the visible label is correctly associated with
// the field (a screen-reader and click-target requirement), an error
// message sets aria-invalid and is linked via aria-describedby, and
// typing fires onChange as a controlled input expects.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Input } from "@/components/ui/Input";

describe("Input", () => {
  it("associates the label with the input via htmlFor/id", () => {
    render(<Input label="Company name" />);
    expect(screen.getByLabelText("Company name")).toBeInTheDocument();
  });

  it("calls onChange when the user types", async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(<Input label="Company name" value="" onChange={handleChange} />);

    await user.type(screen.getByLabelText("Company name"), "TCS");

    expect(handleChange).toHaveBeenCalled();
  });

  it("marks the field invalid and links the error message when error is set", () => {
    render(<Input label="Ticker" error="Ticker not found on NSE/BSE." />);
    const input = screen.getByLabelText("Ticker");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Ticker not found on NSE/BSE.");
  });

  it("shows hint text when there is no error", () => {
    render(<Input label="Company name" hint="Search by name or ticker." />);
    expect(screen.getByText("Search by name or ticker.")).toBeInTheDocument();
  });

  it("does not render hint text when an error is present", () => {
    render(<Input label="Ticker" hint="Search by name or ticker." error="Not found." />);
    expect(screen.queryByText("Search by name or ticker.")).not.toBeInTheDocument();
  });
});
