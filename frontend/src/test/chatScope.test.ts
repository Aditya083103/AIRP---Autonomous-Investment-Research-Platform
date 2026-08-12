// frontend/src/test/chatScope.test.ts
// Tests for src/lib/chat/chatScope.ts (T-105): deriveChatScope must
// return 'memo_scoped' with the correct analysisId for every path
// matching "/analysis/:jobId/memo" (MemoPage, T-063), and
// 'portfolio_wide' with a null analysisId for every other path,
// including paths that merely start with "/analysis" but are not the
// memo route. chatScopeKey must produce equal keys for equal scopes
// and different keys across the memo_scoped/portfolio_wide boundary
// and across two different memo analysisIds.

import { describe, expect, it } from "vitest";

import { chatScopeKey, deriveChatScope } from "@/lib/chat/chatScope";

describe("deriveChatScope", () => {
  it("returns memo_scoped with the jobId for the MemoPage route", () => {
    const scope = deriveChatScope("/analysis/11111111-1111-1111-1111-111111111111/memo");
    expect(scope).toEqual({
      sessionType: "memo_scoped",
      analysisId: "11111111-1111-1111-1111-111111111111",
    });
  });

  it("returns portfolio_wide for the dashboard", () => {
    expect(deriveChatScope("/dashboard")).toEqual({
      sessionType: "portfolio_wide",
      analysisId: null,
    });
  });

  it("returns portfolio_wide for the landing page", () => {
    expect(deriveChatScope("/")).toEqual({ sessionType: "portfolio_wide", analysisId: null });
  });

  it("returns portfolio_wide for the result page (a different /analysis/:jobId route)", () => {
    expect(deriveChatScope("/analysis/11111111-1111-1111-1111-111111111111/result")).toEqual({
      sessionType: "portfolio_wide",
      analysisId: null,
    });
  });

  it("returns portfolio_wide for the bare /analysis input-form route", () => {
    expect(deriveChatScope("/analysis")).toEqual({
      sessionType: "portfolio_wide",
      analysisId: null,
    });
  });

  it("returns portfolio_wide for /compare", () => {
    expect(deriveChatScope("/compare")).toEqual({
      sessionType: "portfolio_wide",
      analysisId: null,
    });
  });
});

describe("chatScopeKey", () => {
  it("is stable for two calls describing the same memo_scoped scope", () => {
    const a = chatScopeKey({ sessionType: "memo_scoped", analysisId: "job-1" });
    const b = chatScopeKey({ sessionType: "memo_scoped", analysisId: "job-1" });
    expect(a).toBe(b);
  });

  it("differs between two different memo analysisIds", () => {
    const a = chatScopeKey({ sessionType: "memo_scoped", analysisId: "job-1" });
    const b = chatScopeKey({ sessionType: "memo_scoped", analysisId: "job-2" });
    expect(a).not.toBe(b);
  });

  it("differs between memo_scoped and portfolio_wide", () => {
    const memo = chatScopeKey({ sessionType: "memo_scoped", analysisId: "job-1" });
    const portfolio = chatScopeKey({ sessionType: "portfolio_wide", analysisId: null });
    expect(memo).not.toBe(portfolio);
  });
});
