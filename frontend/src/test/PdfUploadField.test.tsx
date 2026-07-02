// frontend/src/test/PdfUploadField.test.tsx
// Tests for PdfUploadField (T-058): selecting a file via the hidden
// input shows a filename/size preview, Remove clears it, and a given
// error string renders instead of the default hint.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PdfUploadField } from "@/components/analysis/PdfUploadField";

describe("PdfUploadField", () => {
  it("shows 'No file selected' when there is no file", () => {
    render(<PdfUploadField file={null} onChange={vi.fn()} />);
    expect(screen.getByText("No file selected")).toBeInTheDocument();
  });

  it("shows the filename and size when a file is selected", () => {
    const file = new File([new Uint8Array(2 * 1024 * 1024)], "annual-report.pdf", {
      type: "application/pdf",
    });
    render(<PdfUploadField file={file} onChange={vi.fn()} />);

    expect(screen.getByText("annual-report.pdf")).toBeInTheDocument();
    expect(screen.getByText("(2.0 MB)")).toBeInTheDocument();
  });

  it("calls onChange(null) when Remove is clicked", async () => {
    const handleChange = vi.fn();
    const file = new File(["x"], "annual-report.pdf", { type: "application/pdf" });
    const user = userEvent.setup();
    render(<PdfUploadField file={file} onChange={handleChange} />);

    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(handleChange).toHaveBeenCalledWith(null);
  });

  it("calls onChange with the selected file", async () => {
    const handleChange = vi.fn();
    const file = new File(["x"], "annual-report.pdf", { type: "application/pdf" });
    const user = userEvent.setup();
    const { container } = render(<PdfUploadField file={null} onChange={handleChange} />);

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input as HTMLInputElement, file);

    expect(handleChange).toHaveBeenCalledWith(file);
  });

  it("shows a validation error instead of the default hint", () => {
    render(
      <PdfUploadField file={null} onChange={vi.fn()} error="PDF must be smaller than 10MB." />,
    );

    expect(screen.getByText("PDF must be smaller than 10MB.")).toBeInTheDocument();
    expect(screen.queryByText("PDF only, up to 10MB.")).not.toBeInTheDocument();
  });
});
