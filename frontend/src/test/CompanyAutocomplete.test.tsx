// frontend/src/test/CompanyAutocomplete.test.tsx
// Tests for CompanyAutocomplete (T-058): typing filters the option
// list by name or ticker, selecting an option (by click or by
// keyboard) calls onChange with the full NseCompany, and a validation
// error renders when given one.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CompanyAutocomplete } from "@/components/analysis/CompanyAutocomplete";
import { type NseCompany } from "@/data/nseTop50";

const OPTIONS: NseCompany[] = [
  { name: "Infosys", ticker: "INFY.NS", exchange: "NSE" },
  { name: "Tata Consultancy Services", ticker: "TCS.NS", exchange: "NSE" },
  { name: "ICICI Bank", ticker: "ICICIBANK.NS", exchange: "NSE" },
];

describe("CompanyAutocomplete", () => {
  it("shows options when the input is focused", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete label="Company" value={null} onChange={vi.fn()} options={OPTIONS} />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));

    expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument();
  });

  it("filters options by name as the user types", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete label="Company" value={null} onChange={vi.fn()} options={OPTIONS} />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "infosys");

    expect(screen.getByRole("option", { name: /infosys/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /tata consultancy/i })).not.toBeInTheDocument();
  });

  it("filters options by ticker as the user types", async () => {
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete label="Company" value={null} onChange={vi.fn()} options={OPTIONS} />,
    );

    await user.type(screen.getByRole("combobox", { name: "Company" }), "TCS");

    expect(screen.getByRole("option", { name: /tata consultancy/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /infosys/i })).not.toBeInTheDocument();
  });

  it("calls onChange with the full company object when an option is clicked", async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={handleChange}
        options={OPTIONS}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Company" }));
    await user.click(screen.getByRole("option", { name: /infosys/i }));

    expect(handleChange).toHaveBeenCalledWith(OPTIONS[0]);
  });

  it("selects the highlighted option on Enter", async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={handleChange}
        options={OPTIONS}
      />,
    );

    const input = screen.getByRole("combobox", { name: "Company" });
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");

    expect(handleChange).toHaveBeenCalledWith(OPTIONS[1]);
  });

  it("shows a validation error message when given one", () => {
    render(
      <CompanyAutocomplete
        label="Company"
        value={null}
        onChange={vi.fn()}
        options={OPTIONS}
        error="Select a company from the list."
      />,
    );

    expect(screen.getByText("Select a company from the list.")).toBeInTheDocument();
  });
});
