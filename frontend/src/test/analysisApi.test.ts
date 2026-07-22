// frontend/src/test/analysisApi.test.ts
// Tests for src/api/analysis.ts (T-057, extended in T-058): request
// shape (URL, query params, Authorization header, multipart body) and
// AnalysisApiError message extraction, mirroring test/authApi.test.ts's
// approach for the same two FastAPI error-body shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AnalysisApiError,
  fetchAnalysisCharts,
  fetchAnalysisHistory,
  fetchAnalysisMemoPdf,
  fetchAnalysisResult,
  startAnalysis,
  uploadDocument,
} from "@/api/analysis";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const HISTORY_RESPONSE = {
  items: [],
  total_count: 0,
  limit: 20,
  offset: 0,
  has_more: false,
};

describe("fetchAnalysisHistory", () => {
  it("sends the Authorization header with the given token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token", limit: 20, offset: 0 });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("includes limit and offset as query params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token", limit: 20, offset: 40 });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/history");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
  });

  it("omits query params that were not given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token" });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith("/analysis/history")).toBe(true);
  });

  it("resolves with the parsed HistoryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisHistory({ accessToken: "jwt-token" });

    expect(result).toEqual(HISTORY_RESPONSE);
  });

  it("throws AnalysisApiError with the backend's detail string on failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Not authenticated" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAnalysisHistory({ accessToken: "bad-token" })).rejects.toThrow(
      "Not authenticated",
    );
  });

  it("throws an AnalysisApiError instance carrying the status code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAnalysisHistory({ accessToken: "jwt-token" }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(AnalysisApiError);
    expect((error as AnalysisApiError).status).toBe(500);
  });
});

const START_RESPONSE = {
  job_id: "11111111-1111-1111-1111-111111111111",
  status: "pending",
  company_name: "Infosys",
  ticker: "INFY.NS",
  exchange: "NSE",
};

describe("startAnalysis", () => {
  it("posts company_name/ticker/exchange/period with the Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await startAnalysis({
      accessToken: "jwt-token",
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/start");
    expect(options.method).toBe("POST");
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    // T-085: period defaults to "1y" when the caller omits it.
    expect(body).toEqual({
      company_name: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
      period: "1y",
    });
  });

  it("posts an explicit period when provided (T-085)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await startAnalysis({
      accessToken: "jwt-token",
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
      period: "5y",
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.period).toBe("5y");
  });

  it("resolves with the parsed AnalysisStartResponse", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, START_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await startAnalysis({
      accessToken: "jwt-token",
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
    });

    expect(result).toEqual(START_RESPONSE);
  });

  it("throws AnalysisApiError on failure", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(422, { detail: "company_name must not be empty" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      startAnalysis({ accessToken: "jwt-token", companyName: "", ticker: "", exchange: "NSE" }),
    ).rejects.toThrow("company_name must not be empty");
  });
});

const UPLOAD_RESPONSE = {
  company_name: "Infosys",
  ticker: "INFY.NS",
  exchange: "NSE",
  source_filename: "annual-report.pdf",
  doc_type: "annual_report",
  chunks_ingested: 12,
};

describe("uploadDocument", () => {
  it("sends a multipart/form-data body with the Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, UPLOAD_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["pdf-bytes"], "annual-report.pdf", { type: "application/pdf" });

    await uploadDocument({
      accessToken: "jwt-token",
      file,
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/documents/upload");
    expect(options.method).toBe("POST");
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
    expect(options.body).toBeInstanceOf(FormData);
    const formData = options.body as FormData;
    expect(formData.get("company_name")).toBe("Infosys");
    expect(formData.get("ticker")).toBe("INFY.NS");
    expect(formData.get("exchange")).toBe("NSE");
    expect((formData.get("file") as File).name).toBe("annual-report.pdf");
  });

  it("does not set a Content-Type header (the browser sets the multipart boundary)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, UPLOAD_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["pdf-bytes"], "annual-report.pdf", { type: "application/pdf" });

    await uploadDocument({
      accessToken: "jwt-token",
      file,
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("resolves with the parsed DocumentUploadResponse", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, UPLOAD_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["pdf-bytes"], "annual-report.pdf", { type: "application/pdf" });

    const result = await uploadDocument({
      accessToken: "jwt-token",
      file,
      companyName: "Infosys",
      ticker: "INFY.NS",
      exchange: "NSE",
    });

    expect(result).toEqual(UPLOAD_RESPONSE);
  });

  it("throws AnalysisApiError with the backend's detail on an oversized upload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(413, { detail: "upload is 25000000 bytes" }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["pdf-bytes"], "big.pdf", { type: "application/pdf" });

    await expect(
      uploadDocument({
        accessToken: "jwt-token",
        file,
        companyName: "Infosys",
        ticker: "INFY.NS",
        exchange: "NSE",
      }),
    ).rejects.toThrow("upload is 25000000 bytes");
  });
});

const RESULT_RESPONSE = {
  agent_name: "portfolio_manager",
  analysis_id: "11111111-1111-1111-1111-111111111111",
  company_name: "Infosys",
  ticker: "INFY.NS",
  generated_at: "2026-06-15T10:30:00Z",
  error: null,
  verdict: "BUY",
  conviction_score: 8,
  price_target: "₹1,800 (12-month)",
  time_horizon: "12 months",
  executive_summary: "Infosys shows strong deal momentum.",
  investment_thesis: "Digital transformation demand supports growth.",
  bull_case: "Large deal wins accelerating.",
  bear_case: "Margin pressure from wage hikes.",
  risk_summary: "Client concentration in BFSI and manufacturing.",
  valuation_summary: "Trading below historical average multiples.",
  key_risks: ["Client concentration"],
  key_catalysts: ["Large deal pipeline"],
  contrarian_response: "Margin concern addressed by cost optimisation plan.",
  debate_rounds_used: 2,
  agent_weights: { fundamental_analyst: 0.3 },
  summary: "Infosys: BUY with conviction 8/10.",
};

describe("fetchAnalysisResult", () => {
  it("sends the Authorization header with the given token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisResult({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("requests GET /analysis/{job_id}/result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisResult({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/11111111-1111-1111-1111-111111111111/result");
    expect(options.method).toBe("GET");
  });

  it("resolves with the parsed InvestmentDecisionResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, RESULT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisResult({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    expect(result).toEqual(RESULT_RESPONSE);
  });

  it("throws AnalysisApiError with the backend's detail on a 409 (not ready)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "Analysis job_id=... is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchAnalysisResult({ accessToken: "jwt-token", jobId: "not-ready-job" }),
    ).rejects.toThrow("Analysis job_id=... is not ready yet");
  });

  it("throws an AnalysisApiError instance carrying the 404 status code", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "No analysis job found" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAnalysisResult({
      accessToken: "jwt-token",
      jobId: "missing-job",
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AnalysisApiError);
    expect((error as AnalysisApiError).status).toBe(404);
  });
});

const CHART_DATA_RESPONSE = {
  job_id: "11111111-1111-1111-1111-111111111111",
  ticker: "INFY.NS",
  company_name: "Infosys",
  price_currency: "INR",
  price_history: [{ date: "2026-06-18", close: 1780.5, volume: 1_000_000 }],
  financials: [{ fiscal_year: "FY 2024", revenue_crores: 153_670.0, net_income_crores: 26_233.0 }],
  valuation: {
    pe_ratio: 24.1,
    sector_avg_pe: 22.5,
    pb_ratio: 8.2,
    sector_avg_pb: 7.9,
    ev_ebitda: 15.3,
    sector_avg_ev_ebitda: 14.8,
    peer_tickers: ["TCS.NS", "WIPRO.NS"],
  },
  sentiment: {
    sentiment_score: 0.18,
    sentiment_label: "positive",
    articles_analysed: 19,
    positive_articles: 9,
    negative_articles: 4,
    neutral_articles: 6,
  },
  risk: {
    risk_score: 3,
    governance_risk: 2,
    regulatory_risk: 2,
    financial_risk: 4,
    concentration_risk: 5,
  },
  data_warnings: [],
};

describe("fetchAnalysisCharts", () => {
  it("sends the Authorization header with the given token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisCharts({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("requests GET /analysis/{job_id}/charts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisCharts({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/11111111-1111-1111-1111-111111111111/charts");
    expect(options.method).toBe("GET");
  });

  it("resolves with the parsed AnalysisChartDataResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisCharts({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    expect(result).toEqual(CHART_DATA_RESPONSE);
  });

  it("resolves successfully when a source is null (partial degradation)", async () => {
    const degraded = {
      ...CHART_DATA_RESPONSE,
      valuation: null,
      data_warnings: ["Valuation data was not available for this analysis."],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, degraded));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisCharts({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    expect(result.valuation).toBeNull();
    expect(result.data_warnings).toHaveLength(1);
  });

  it("throws AnalysisApiError with the backend's detail on a 409 (not ready)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "Analysis job_id=... is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchAnalysisCharts({ accessToken: "jwt-token", jobId: "not-ready-job" }),
    ).rejects.toThrow("Analysis job_id=... is not ready yet");
  });

  it("throws an AnalysisApiError instance carrying the 404 status code", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "No analysis job found" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAnalysisCharts({
      accessToken: "jwt-token",
      jobId: "missing-job",
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AnalysisApiError);
    expect((error as AnalysisApiError).status).toBe(404);
  });
});

describe("fetchAnalysisMemoPdf", () => {
  // jsdom (the Vitest test environment configured in vitest.config.ts)
  // installs its own `Blob` on `globalThis`, which is a different class
  // from the Blob implementation Node's underlying fetch/undici internals
  // construct when a real `Response`'s `.blob()` is called. A `Response`
  // built from a Blob body and then read back via `.blob()` therefore
  // returns an instance that fails `toBeInstanceOf(Blob)` against jsdom's
  // `Blob` global, even though nothing is actually broken. Overriding
  // `.blob()` to resolve with the exact Blob instance the test constructed
  // sidesteps the cross-realm mismatch entirely.
  function pdfResponse(status: number, body: BodyInit | null = new Blob(["%PDF-fake"])): Response {
    const response = new Response(body, { status });
    const blobBody = body instanceof Blob ? body : new Blob([String(body ?? "")]);
    response.blob = vi.fn().mockResolvedValue(blobBody);
    return response;
  }

  it("sends a GET request with the Authorization header to the memo/pdf route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pdfResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisMemoPdf({
      accessToken: "jwt-token",
      jobId: "11111111-1111-1111-1111-111111111111",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/11111111-1111-1111-1111-111111111111/memo/pdf");
    expect(options.method).toBe("GET");
    expect((options.headers as Record<string, string>).Authorization).toBe("Bearer jwt-token");
  });

  it("resolves with a Blob on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pdfResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisMemoPdf({ accessToken: "jwt-token", jobId: "job-1" });

    expect(result).toBeInstanceOf(Blob);
  });

  it("throws AnalysisApiError with the backend's detail when no PDF exists", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(pdfResponse(404, JSON.stringify({ detail: "No PDF has been generated" })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchAnalysisMemoPdf({ accessToken: "jwt-token", jobId: "job-1" }),
    ).rejects.toThrow("No PDF has been generated");
  });
});
