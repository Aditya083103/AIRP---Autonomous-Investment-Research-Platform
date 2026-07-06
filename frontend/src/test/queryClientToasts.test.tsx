// frontend/src/test/queryClientToasts.test.tsx
// Tests for src/lib/queryClient.ts's T-066 QueryCache/MutationCache
// wiring -- this is the mechanism behind "every API error shows a
// toast" holding for pages that never call `toast.error(...)`
// themselves (DashboardPage, AnalysisResultPage, MemoPage, and
// ComparePage's per-side panels all just use useQuery/useMutation and
// get this for free).
//
// Deliberately imports the real exported `queryClient` singleton
// (the exact instance AppProviders.tsx wires up), not a fresh
// `new QueryClient(...)` the way most other page tests do -- a fresh
// client would not have this file's onError handlers at all, so it
// would prove nothing about the actual wiring. Because it's a shared
// singleton, every test clears its cache and the toast store in
// afterEach so one test's queries/toasts can't leak into the next.

import { QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { queryClient } from "@/lib/queryClient";
import { toastStore } from "@/lib/toastStore";

afterEach(() => {
  queryClient.clear();
  toastStore.clear();
});

function FailingQueryProbe(): JSX.Element {
  const { isError } = useQuery({
    queryKey: ["toast-test-query"],
    queryFn: () => Promise.reject(new Error("Query failed on purpose")),
    retry: false,
  });
  return <p>{isError ? "query errored" : "query pending or ok"}</p>;
}

function FailingMutationProbe(): JSX.Element {
  const mutation = useMutation({
    mutationFn: () => Promise.reject(new Error("Mutation failed on purpose")),
  });
  return (
    <button type="button" onClick={() => mutation.mutate()}>
      Trigger mutation
    </button>
  );
}

describe("queryClient toast wiring", () => {
  it("shows an error toast when a query permanently fails", async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <FailingQueryProbe />
      </QueryClientProvider>,
    );

    await screen.findByText("query errored");

    expect(toastStore.getSnapshot()).toContainEqual(
      expect.objectContaining({ tone: "error", message: "Query failed on purpose" }),
    );
  });

  it("shows an error toast when a mutation fails", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <FailingMutationProbe />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Trigger mutation" }));

    await waitFor(() =>
      expect(toastStore.getSnapshot()).toContainEqual(
        expect.objectContaining({ tone: "error", message: "Mutation failed on purpose" }),
      ),
    );
  });
});
