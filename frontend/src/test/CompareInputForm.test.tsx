// frontend/src/test/CompareInputForm.test.tsx
// Tests for CompareInputForm (T-064). Same interaction pattern
// AnalysisPage.test.tsx already uses for CompanyAutocomplete (click,
// type, click the option) doubled for the two company fields.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CompareInputForm } from "@/components/compare/CompareInputForm";

async function selectCompany(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
  query: string,
  optionPattern: RegExp,
): Promise<void> {
  const combobox = screen.getByRole("combobox", { name: label });
  await user.click(combobox);
  await user.type(combobox, query);
  await user.click(screen.getByRole("option", { name: optionPattern }));
}

describe("CompareInputForm", () => {
  it("shows validation errors when submitted with nothing selected", async () => {
    const user = userEvent.setup();
    render(<CompareInputForm onSubmit={vi.fn()} isSubmitting={false} />);

    await user.click(screen.getByRole("button", { name: /compare companies/i }));

    expect(await screen.findByText("Select the first company.")).toBeInTheDocument();
    expect(await screen.findByText("Select the second company.")).toBeInTheDocument();
  });

  it("rejects selecting the same company for both sides", async () => {
    const user = userEvent.setup();
    render(<CompareInputForm onSubmit={vi.fn()} isSubmitting={false} />);

    await selectCompany(user, "Company A", "Infosys", /infosys/i);
    await selectCompany(user, "Company B", "Infosys", /infosys/i);
    await user.click(screen.getByRole("button", { name: /compare companies/i }));

    expect(
      await screen.findByText("Choose two different companies to compare."),
    ).toBeInTheDocument();
  });

  it("calls onSubmit with both companies once two distinct companies are selected", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<CompareInputForm onSubmit={onSubmit} isSubmitting={false} />);

    await selectCompany(user, "Company A", "TCS", /tcs/i);
    await selectCompany(user, "Company B", "Infosys", /infosys/i);
    await user.click(screen.getByRole("button", { name: /compare companies/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [companyA, companyB] = onSubmit.mock.calls[0] as [{ ticker: string }, { ticker: string }];
    expect(companyA.ticker).toBe("TCS.NS");
    expect(companyB.ticker).toBe("INFY.NS");
  });

  it("shows an external form error when provided", () => {
    render(
      <CompareInputForm onSubmit={vi.fn()} isSubmitting={false} formError="Could not start." />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Could not start.");
  });

  it("disables the submit button and shows a spinner while submitting", () => {
    render(<CompareInputForm onSubmit={vi.fn()} isSubmitting={true} />);

    expect(screen.getByRole("button", { name: /compare companies/i })).toBeDisabled();
  });
});
