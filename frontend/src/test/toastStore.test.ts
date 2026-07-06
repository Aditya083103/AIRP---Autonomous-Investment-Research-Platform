// frontend/src/test/toastStore.test.ts
// Tests for src/lib/toastStore.ts and src/lib/toast.ts (T-066). Pure
// module-level state -- no rendering, no network -- so these assert
// directly against toastStore.getSnapshot()/subscribe() the same way
// winnerLogic.test.ts asserts against buildComparisonRows' plain
// return values.

import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisApiError } from "@/api/analysis";
import { toast, toastApiError } from "@/lib/toast";
import { toastStore } from "@/lib/toastStore";

afterEach(() => {
  toastStore.clear();
});

describe("toastStore", () => {
  it("starts empty", () => {
    expect(toastStore.getSnapshot()).toEqual([]);
  });

  it("adds a toast with the given tone and message, and a generated id", () => {
    const id = toastStore.add("error", "Something broke");

    const snapshot = toastStore.getSnapshot();
    expect(snapshot).toHaveLength(1);
    expect(snapshot[0]).toEqual({ id, tone: "error", message: "Something broke" });
  });

  it("appends multiple toasts in call order", () => {
    toastStore.add("info", "First");
    toastStore.add("success", "Second");

    expect(toastStore.getSnapshot().map((t) => t.message)).toEqual(["First", "Second"]);
  });

  it("removes a toast by id without affecting others", () => {
    const firstId = toastStore.add("info", "First");
    const secondId = toastStore.add("info", "Second");

    toastStore.remove(firstId);

    const snapshot = toastStore.getSnapshot();
    expect(snapshot).toHaveLength(1);
    expect(snapshot[0]?.id).toBe(secondId);
  });

  it("does nothing when removing an id that no longer exists", () => {
    toastStore.add("info", "First");
    const before = toastStore.getSnapshot();

    toastStore.remove("not-a-real-id");

    expect(toastStore.getSnapshot()).toEqual(before);
  });

  it("clear() empties the store", () => {
    toastStore.add("info", "First");
    toastStore.add("info", "Second");

    toastStore.clear();

    expect(toastStore.getSnapshot()).toEqual([]);
  });

  it("notifies subscribers on add and remove, and stops after unsubscribing", () => {
    const listener = vi.fn();
    const unsubscribe = toastStore.subscribe(listener);

    const id = toastStore.add("info", "Hello");
    expect(listener).toHaveBeenCalledTimes(1);

    toastStore.remove(id);
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    toastStore.add("info", "Ignored");
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("toast()", () => {
  it("success/error/info each add a toast with the matching tone", () => {
    toast.success("Saved");
    toast.error("Failed");
    toast.info("FYI");

    expect(toastStore.getSnapshot().map((t) => t.tone)).toEqual(["success", "error", "info"]);
  });
});

describe("toastApiError()", () => {
  it("uses an Error's own message", () => {
    toastApiError(new AnalysisApiError(500, "Something broke"));

    expect(toastStore.getSnapshot()[0]?.message).toBe("Something broke");
  });

  it("falls back to a generic message for a non-Error throw", () => {
    toastApiError("just a string, not an Error");

    expect(toastStore.getSnapshot()[0]?.message).toBe("Something went wrong. Please try again.");
  });
});
