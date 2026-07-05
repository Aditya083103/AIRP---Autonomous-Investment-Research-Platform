// frontend/src/test/useDownloadMemoPdf.test.ts
// Tests for useDownloadMemoPdf (T-063). Same renderHook +
// QueryClientProvider approach as useAnalysisResult.test.tsx, plus
// stubs for URL.createObjectURL/revokeObjectURL and
// HTMLAnchorElement.click -- jsdom does not implement Blob object URLs
// and this hook's whole job is driving a synthetic <a download> click.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDownloadMemoPdf } from "@/hooks/useDownloadMemoPdf";

function pdfResponse(status: number, body: BodyInit | null = new Blob(["%PDF-fake"])): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": status === 200 ? "application/pdf" : "application/json" },
  });
}

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useDownloadMemoPdf", () => {
  it("fetches the PDF with the Authorization header and triggers a download", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pdfResponse(200));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    const { result } = renderHook(() => useDownloadMemoPdf(), { wrapper });

    result.current.mutate({ accessToken: "jwt-token", jobId: "job-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/job-1/memo/pdf");
    expect((options.headers as Record<string, string>).Authorization).toBe("Bearer jwt-token");
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("surfaces an error when the backend has no PDF for this job", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(pdfResponse(404, JSON.stringify({ detail: "No PDF has been generated" })));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useDownloadMemoPdf(), { wrapper });

    result.current.mutate({ accessToken: "jwt-token", jobId: "job-1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("No PDF has been generated");
  });
});
