// frontend/src/test/analysisApi.test.ts
// Tests for src/api/analysis.ts (T-057, extended in T-058): request
// shape (URL, query params, Authorization header, multipart body) and
// AnalysisApiError message extraction, mirroring test/authApi.test.ts's
// approach for the same two FastAPI error-body shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AnalysisApiError,
  fetchAnalysisHistory,
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
  it("posts company_name/ticker/exchange with the Authorization header", async () => {
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
    expect(body).toEqual({ company_name: "Infosys", ticker: "INFY.NS", exchange: "NSE" });
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
