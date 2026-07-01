// frontend/src/components/ui/Modal.test.tsx
// Tests for Modal (T-054): renders nothing when closed, and when open
// responds to all three documented dismiss paths -- Escape key, backdrop
// click, and the built-in close button -- each calling the same onClose.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "@/components/ui/Modal";

describe("Modal", () => {
  it("renders nothing when isOpen is false", () => {
    render(
      <Modal isOpen={false} onClose={vi.fn()} title="Delete this analysis?">
        Body content
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the title and body content when open", () => {
    render(
      <Modal isOpen onClose={vi.fn()} title="Delete this analysis?">
        This cannot be undone.
      </Modal>,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete this analysis?")).toBeInTheDocument();
    expect(screen.getByText("This cannot be undone.")).toBeInTheDocument();
  });

  it("calls onClose when the Escape key is pressed", async () => {
    const handleClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={handleClose} title="Delete this analysis?">
        Body
      </Modal>,
    );

    await user.keyboard("{Escape}");

    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the close button is clicked", async () => {
    const handleClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={handleClose} title="Delete this analysis?">
        Body
      </Modal>,
    );

    await user.click(screen.getByRole("button", { name: "Close dialog" }));

    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the backdrop is clicked", async () => {
    const handleClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={handleClose} title="Delete this analysis?">
        Body
      </Modal>,
    );

    // The backdrop is the dialog's parent element (the fixed-position overlay).
    const backdrop = screen.getByRole("dialog").parentElement;
    expect(backdrop).not.toBeNull();
    if (backdrop) {
      await user.click(backdrop);
    }

    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking inside the dialog panel", async () => {
    const handleClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Modal isOpen onClose={handleClose} title="Delete this analysis?">
        Body content
      </Modal>,
    );

    await user.click(screen.getByText("Body content"));

    expect(handleClose).not.toHaveBeenCalled();
  });
});
