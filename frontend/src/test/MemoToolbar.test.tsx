// frontend/src/test/MemoToolbar.test.tsx
// Tests for MemoToolbar (T-063): the Download PDF button calls the
// memo/pdf endpoint with the given jobId/accessToken, and the Share
// button copies the current URL via navigator.clipboard and shows
// transient "Link copied!" feedback.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoToolbar } from "@/components/memo/MemoToolbar";

function pdfResponse(status: number, body: BodyInit | null = new Blob(["%PDF-fake"])): Response {
  return new Response(body, { status });
}

function renderToolbar(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoToolbar accessToken="jwt-token" jobId="job-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("MemoToolbar", () => {
  it("requests the memo PDF for the given job when Download PDF is clicked", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pdfResponse(200));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderToolbar();
    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/analysis/job-1/memo/pdf");
  });

  it("shows a PDF download error inline without crashing the toolbar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(pdfResponse(404, JSON.stringify({ detail: "No PDF available" }))),
    );

    renderToolbar();
    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));

    expect(await screen.findByText("No PDF available")).toBeInTheDocument();
  });

  it("copies the current URL to the clipboard and shows confirmation when Share is clicked", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    renderToolbar();
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href));
    expect(await screen.findByText("Link copied!")).toBeInTheDocument();
  });

  it("shows an error message if copying to the clipboard fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    renderToolbar();
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    const expectedMessage =
      "Could not copy the link. Please copy it from your browser's address bar.";
    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
  });
});
