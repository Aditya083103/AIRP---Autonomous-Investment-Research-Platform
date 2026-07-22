// frontend/src/test/analysisSchemas.test.ts
// Tests for src/lib/validation/analysisSchemas.ts (T-058): the
// companyTicker schema and the standalone PDF validation helpers.

import { describe, expect, it } from "vitest";

import {
  ANALYSIS_HORIZONS,
  analysisInputSchema,
  DEFAULT_ANALYSIS_HORIZON,
  isPdfFile,
  isPdfWithinSizeLimit,
  MAX_PDF_UPLOAD_BYTES,
} from "@/lib/validation/analysisSchemas";

describe("analysisInputSchema", () => {
  it("accepts a non-empty ticker", () => {
    const result = analysisInputSchema.safeParse({ companyTicker: "INFY.NS" });
    expect(result.success).toBe(true);
  });

  it("rejects an empty ticker (nothing selected)", () => {
    const result = analysisInputSchema.safeParse({ companyTicker: "" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.message).toBe("Select a company from the list.");
    }
  });

  it("rejects a missing companyTicker field", () => {
    const result = analysisInputSchema.safeParse({});
    expect(result.success).toBe(false);
  });
});

// T-085 -- Analysis Horizon selector
describe("analysisInputSchema horizon field", () => {
  it("defaults horizon to '1y' when omitted", () => {
    const result = analysisInputSchema.safeParse({ companyTicker: "INFY.NS" });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.horizon).toBe(DEFAULT_ANALYSIS_HORIZON);
    }
  });

  it("accepts every supported horizon", () => {
    for (const horizon of ANALYSIS_HORIZONS) {
      const result = analysisInputSchema.safeParse({ companyTicker: "INFY.NS", horizon });
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.horizon).toBe(horizon);
      }
    }
  });

  it("rejects an unsupported horizon", () => {
    const result = analysisInputSchema.safeParse({
      companyTicker: "INFY.NS",
      horizon: "15y",
    });
    expect(result.success).toBe(false);
  });
});

describe("isPdfFile", () => {
  it("accepts application/pdf", () => {
    const file = new File(["x"], "report.pdf", { type: "application/pdf" });
    expect(isPdfFile(file)).toBe(true);
  });

  it("accepts application/octet-stream (some browsers report PDFs this way)", () => {
    const file = new File(["x"], "report.pdf", { type: "application/octet-stream" });
    expect(isPdfFile(file)).toBe(true);
  });

  it("rejects other content types", () => {
    const file = new File(["x"], "report.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    expect(isPdfFile(file)).toBe(false);
  });
});

describe("isPdfWithinSizeLimit", () => {
  it("accepts a file at exactly the limit", () => {
    const file = new File([new Uint8Array(MAX_PDF_UPLOAD_BYTES)], "report.pdf", {
      type: "application/pdf",
    });
    expect(isPdfWithinSizeLimit(file)).toBe(true);
  });

  it("rejects a file over the limit", () => {
    const file = new File([new Uint8Array(MAX_PDF_UPLOAD_BYTES + 1)], "report.pdf", {
      type: "application/pdf",
    });
    expect(isPdfWithinSizeLimit(file)).toBe(false);
  });
});
