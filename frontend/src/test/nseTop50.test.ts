// frontend/src/test/nseTop50.test.ts
// Tests for src/data/nseTop50.ts (T-058): guards the acceptance
// criterion's literal "top 50" -- exactly 50 entries, every ticker
// unique, and every entry shaped correctly for
// CompanyAutocomplete/startAnalysis to consume.

import { describe, expect, it } from "vitest";

import { NSE_TOP_50 } from "@/data/nseTop50";

describe("NSE_TOP_50", () => {
  it("has exactly 50 companies", () => {
    expect(NSE_TOP_50).toHaveLength(50);
  });

  it("has a unique ticker per entry", () => {
    const tickers = NSE_TOP_50.map((company) => company.ticker);
    expect(new Set(tickers).size).toBe(tickers.length);
  });

  it("gives every ticker the .NS Yahoo Finance suffix", () => {
    for (const company of NSE_TOP_50) {
      expect(company.ticker.endsWith(".NS")).toBe(true);
    }
  });

  it("sets exchange to 'NSE' for every entry", () => {
    for (const company of NSE_TOP_50) {
      expect(company.exchange).toBe("NSE");
    }
  });

  it("gives every entry a non-empty display name", () => {
    for (const company of NSE_TOP_50) {
      expect(company.name.trim().length).toBeGreaterThan(0);
    }
  });
});
