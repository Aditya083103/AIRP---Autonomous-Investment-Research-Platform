// frontend/src/test/ToastViewport.test.tsx
// Tests for ToastViewport + Toast (T-066). toastStore is a module-level
// singleton (see its own docstring on why), so every test clears it in
// afterEach to avoid one test's toasts leaking into the next.

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastViewport } from "@/components/toast";
import { toastStore } from "@/lib/toastStore";

afterEach(() => {
  toastStore.clear();
  vi.useRealTimers();
});

describe("ToastViewport", () => {
  it("renders nothing visible when there are no toasts", () => {
    render(<ToastViewport />);

    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("renders a toast pushed to the store", () => {
    render(<ToastViewport />);

    act(() => {
      toastStore.add("error", "Could not load your analysis history.");
    });

    expect(screen.getByText("Could not load your analysis history.")).toBeInTheDocument();
  });

  it("renders multiple toasts in the order they were added", () => {
    render(<ToastViewport />);

    act(() => {
      toastStore.add("info", "First");
      toastStore.add("success", "Second");
    });

    const toasts = screen.getAllByTestId("toast");
    expect(toasts).toHaveLength(2);
    expect(toasts[0]).toHaveTextContent("First");
    expect(toasts[1]).toHaveTextContent("Second");
  });

  it("uses role=alert for an error toast and role=status for others", () => {
    render(<ToastViewport />);

    act(() => {
      toastStore.add("error", "Error toast");
      toastStore.add("success", "Success toast");
    });

    expect(screen.getByText("Error toast").closest('[data-testid="toast"]')).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByText("Success toast").closest('[data-testid="toast"]')).toHaveAttribute(
      "role",
      "status",
    );
  });

  it("removes a toast from the store when its dismiss button is clicked", async () => {
    const user = userEvent.setup();
    render(<ToastViewport />);
    act(() => {
      toastStore.add("info", "Dismiss me");
    });

    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));

    expect(screen.queryByText("Dismiss me")).not.toBeInTheDocument();
    expect(toastStore.getSnapshot()).toEqual([]);
  });

  it("auto-dismisses a toast after its timeout elapses", () => {
    vi.useFakeTimers();
    render(<ToastViewport />);
    act(() => {
      toastStore.add("info", "Fading away");
    });

    expect(screen.getByText("Fading away")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(6000);
    });

    expect(screen.queryByText("Fading away")).not.toBeInTheDocument();
    expect(toastStore.getSnapshot()).toEqual([]);
  });
});
