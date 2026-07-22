// frontend/src/test/AnalysisPage.test.tsx
// Tests for AnalysisPage (T-058). Wraps a fake AuthContext (accessToken
// present, matching ProtectedRoute already gating this page in
// AppRoutes.tsx) + MemoryRouter, and mocks global.fetch the same way
// every other API-calling test in this suite does.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { toastStore } from "@/lib/toastStore";
import { AnalysisPage } from "@/pages/AnalysisPage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AUTH_VALUE: AuthContextValue = {
  user: {
    id: "1",
    email: "a@example.com",
    display_name: "Aditya",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
  accessToken: "jwt-token",
  isAuthenticated: true,
  register: async () => {},
  login: async () => {},
  logout: async () => {},
};

function renderAnalysisPage(): ReturnType<typeof render> {
  return render(
    <AuthContext.Provider value={AUTH_VALUE}>
      <MemoryRouter initialEntries={["/analysis"]}>
        <Routes>
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/analysis/:jobId/result" element={<p>Result page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

const START_RESPONSE = {
  job_id: "11111111-1111-1111-1111-111111111111",
  status: "pending",
  company_name: "Infosys",
  ticker: "INFY.NS",
  exchange: "NSE",
};

async function selectInfosys(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole("combobox", { name: "Company" }));
  await user.type(screen.getByRole("combobox", { name: "Company" }), "Infosys");
  await user.click(screen.getByRole("option", { name: /infosys/i }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastStore.clear();
});

describe("AnalysisPage", () => {
  it("shows a validation error when submitted with no company selected", async () => {
    const user = userEvent.setup();
    renderAnalysisPage();

    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    expect(await screen.findByText("Select a company from the list.")).toBeInTheDocument();
  });

  it("starts the analysis and navigates to the result page on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAnalysisPage();

    await selectInfosys(user);
    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    await waitFor(() => expect(screen.getByText("Result page")).toBeInTheDocument());
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/start");
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    // T-085: period is always sent, defaulting to "1y" when the
    // horizon selector is left untouched.
    expect(body).toEqual({
      company_name: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
      period: "1y",
    });
  });

  it("sends the selected analysis horizon (T-085)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAnalysisPage();

    await selectInfosys(user);
    await user.selectOptions(screen.getByRole("combobox", { name: "Analysis horizon" }), "5y");
    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    await waitFor(() => expect(screen.getByText("Result page")).toBeInTheDocument());
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.period).toBe("5y");
  });

  it("shows the backend's error message when starting the analysis fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(500, { detail: "Pipeline is overloaded" })),
    );
    const user = userEvent.setup();
    renderAnalysisPage();

    await selectInfosys(user);
    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    expect(await screen.findByText("Pipeline is overloaded")).toBeInTheDocument();
    expect(toastStore.getSnapshot()).toContainEqual(
      expect.objectContaining({ tone: "error", message: "Pipeline is overloaded" }),
    );
  });

  it("rejects an oversized PDF and disables the submit button", async () => {
    const user = userEvent.setup();
    const { container } = renderAnalysisPage();
    const oversized = new File([new Uint8Array(11 * 1024 * 1024)], "big.pdf", {
      type: "application/pdf",
    });

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, oversized);

    expect(await screen.findByText("PDF must be smaller than 10MB.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start analysis/i })).toBeDisabled();
  });

  it("uploads the PDF before starting the analysis when one is attached", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(201, {
          company_name: "Infosys",
          ticker: "INFY.NS",
          exchange: "NSE",
          source_filename: "annual-report.pdf",
          doc_type: "annual_report",
          chunks_ingested: 5,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = renderAnalysisPage();

    await selectInfosys(user);
    const file = new File(["pdf-bytes"], "annual-report.pdf", { type: "application/pdf" });
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    await waitFor(() => expect(screen.getByText("Result page")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [firstUrl] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [secondUrl] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(firstUrl).toContain("/documents/upload");
    expect(secondUrl).toContain("/analysis/start");
  });

  it("does not start the analysis when the PDF upload fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(413, { detail: "upload is too large" }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = renderAnalysisPage();

    await selectInfosys(user);
    const file = new File(["pdf-bytes"], "annual-report.pdf", { type: "application/pdf" });
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: /start analysis/i }));

    expect(await screen.findByText("upload is too large")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
