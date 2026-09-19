// frontend/src/test/AccuracyPreviewSection.test.tsx
// Tests for AccuracyPreviewSection (landing-page redesign): live numbers
// from GET /api/v1/accuracy/summary (mocked global.fetch, same approach
// as AccuracyPage.test.tsx / useAccuracySummary.test.tsx), an honest
// in-progress state when nothing has been scored yet, and a CTA linking
// to the full /accuracy page.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccuracyPreviewSection } from "@/components/landing/AccuracyPreviewSection";

// AnimatedNumber counts up from 0 on mount when motion is allowed (see
// AccuracySummaryStats.test.tsx's identical note) -- stub reduced motion
// so every numeric assertion below is synchronous, not animation-timing
// dependent.
function stubReducedMotion(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const EMPTY_SUMMARY_RESPONSE = {
  total_evaluated: 0,
  total_pending: 3,
  overall_accuracy_pct: null,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "HOLD", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
    { verdict: "SELL", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
  ],
  by_conviction: [],
};

const POPULATED_SUMMARY_RESPONSE = {
  total_evaluated: 10,
  total_pending: 2,
  overall_accuracy_pct: 70.0,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 5, correct_count: 4, accuracy_pct: 80.0 },
    { verdict: "HOLD", evaluated_count: 3, correct_count: 2, accuracy_pct: 66.67 },
    { verdict: "SELL", evaluated_count: 2, correct_count: 1, accuracy_pct: 50.0 },
  ],
  by_conviction: [],
};

function renderSection(response: Response): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AccuracyPreviewSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubReducedMotion();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AccuracyPreviewSection", () => {
  it("fetches the real accuracy summary endpoint, not a static value", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, POPULATED_SUMMARY_RESPONSE));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AccuracyPreviewSection />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/accuracy/summary"),
      expect.anything(),
    );
  });

  it("renders the live overall accuracy percentage once loaded", async () => {
    renderSection(jsonResponse(200, POPULATED_SUMMARY_RESPONSE));
    expect(await screen.findByText("70.0%")).toBeInTheDocument();
  });

  it("shows an honest in-progress message when nothing has been scored yet", async () => {
    renderSection(jsonResponse(200, EMPTY_SUMMARY_RESPONSE));
    expect(await screen.findByText(/not enough scored verdicts yet/i)).toBeInTheDocument();
    expect(screen.getByText(/3 verdicts are currently waiting/i)).toBeInTheDocument();
  });

  it("shows an error message when the request fails", async () => {
    renderSection(jsonResponse(500, { detail: "Summary is temporarily unavailable" }));
    expect(await screen.findByText("Summary is temporarily unavailable")).toBeInTheDocument();
  });

  it("links its CTA to the full accuracy dashboard", async () => {
    renderSection(jsonResponse(200, POPULATED_SUMMARY_RESPONSE));
    await screen.findByText("70.0%");
    expect(screen.getByRole("link", { name: /see the full accuracy dashboard/i })).toHaveAttribute(
      "href",
      "/accuracy",
    );
  });
});
