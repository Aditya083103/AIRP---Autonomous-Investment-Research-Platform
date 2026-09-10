// frontend/src/components/ui/Modal.test.tsx
// Tests for Modal (T-054): renders nothing when closed, and when open
// responds to all three documented dismiss paths -- Escape key, backdrop
// click, and the built-in close button -- each calling the same onClose.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
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

describe("Modal focus management (Section C audit finding, deferred from unit 9)", () => {
  it("restores focus to the element that opened the dialog after it closes", async () => {
    const user = userEvent.setup();

    function Harness(): JSX.Element {
      const [isOpen, setIsOpen] = useState(false);
      return (
        <div>
          <button type="button" onClick={() => setIsOpen(true)}>
            Open dialog
          </button>
          <Modal isOpen={isOpen} onClose={() => setIsOpen(false)} title="Delete this analysis?">
            Body
          </Modal>
        </div>
      );
    }

    render(<Harness />);
    const openButton = screen.getByRole("button", { name: "Open dialog" });
    openButton.focus();
    expect(openButton).toHaveFocus();

    await user.click(openButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(openButton).toHaveFocus());
  });

  it("wraps Tab from the last focusable element back to the first, trapping focus inside the dialog", async () => {
    const user = userEvent.setup();
    render(
      <Modal
        isOpen
        onClose={vi.fn()}
        title="Delete this analysis?"
        footer={
          <>
            <button type="button">Cancel</button>
            <button type="button">Confirm</button>
          </>
        }
      >
        Body
      </Modal>,
    );

    const closeButton = screen.getByRole("button", { name: "Close dialog" });
    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    const confirmButton = screen.getByRole("button", { name: "Confirm" });

    confirmButton.focus();
    expect(confirmButton).toHaveFocus();

    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(confirmButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(cancelButton).toHaveFocus();
  });

  it("does not let Tab escape the dialog into the page behind it", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <button type="button">Outside button</button>
        <Modal isOpen onClose={vi.fn()} title="Delete this analysis?">
          Body
        </Modal>
      </div>,
    );

    const outsideButton = screen.getByRole("button", { name: "Outside button" });
    const closeButton = screen.getByRole("button", { name: "Close dialog" });

    closeButton.focus();
    await user.tab();

    expect(outsideButton).not.toHaveFocus();
    expect(closeButton).toHaveFocus();
  });
});
