// frontend/src/lib/chat/chatScope.ts
// AIRP -- Chat scope derivation (T-105)
//
// ChatWidget is mounted once in RootLayout.tsx and stays rendered
// across every route (that is what "widget available on Dashboard and
// MemoPage" -- a single always-mounted floating panel, not a
// page-local component -- means in practice). It still has to know,
// on every render, whether the person is currently looking at one
// specific memo (MemoPage, route "/analysis/:jobId/memo") or anywhere
// else, and if the former, which analysis_id to scope the session to.
//
// Rather than requiring MemoPage.tsx (T-063, already shipped and
// tested) to push its jobId into some new shared context, this reads
// the answer directly off the current URL via react-router-dom's own
// matchPath -- the same "read route state directly" approach
// RootLayout.tsx already uses (useLocation, to close the mobile nav
// panel on navigation). This keeps the two-way coupling to exactly
// one direction (chat reads the route; MemoPage is untouched) and
// keeps this task's diff to files ChatWidget actually owns.
//
// Pulled out as its own pure, dependency-light function (rather than
// inlined in useChatWidget.ts) so it is trivially unit-testable
// without rendering anything or mocking useLocation.

import { matchPath } from "react-router-dom";

import { type ChatSessionType } from "@/types/chat";

/** Must stay in sync with AppRoutes.tsx's "analysis/:jobId/memo" route. */
const MEMO_ROUTE_PATTERN = "/analysis/:jobId/memo";

export interface ChatScope {
  sessionType: ChatSessionType;
  /** The scoped analysis's UUID when sessionType is 'memo_scoped', else null. */
  analysisId: string | null;
}

/**
 * Derive the chat scope for the given route pathname.
 *
 * Returns `{ sessionType: "memo_scoped", analysisId: jobId }` for any
 * path matching "/analysis/:jobId/memo" (MemoPage), and
 * `{ sessionType: "portfolio_wide", analysisId: null }` for every
 * other path (Dashboard, the landing page, /analysis, /compare, ...).
 */
export function deriveChatScope(pathname: string): ChatScope {
  const match = matchPath(MEMO_ROUTE_PATTERN, pathname);
  const jobId = match?.params.jobId;

  if (jobId !== undefined && jobId.length > 0) {
    return { sessionType: "memo_scoped", analysisId: jobId };
  }
  return { sessionType: "portfolio_wide", analysisId: null };
}

/**
 * A stable string key identifying one scope "identity" -- two calls
 * with scopes that should share one chat session (or, conversely, two
 * scopes that must NOT share one) compare equal (or not) via this key.
 * Used by useChatWidget.ts to detect "the person navigated to a
 * different memo, or between memo and portfolio mode" and discard the
 * now-stale session rather than reusing it across scopes.
 */
export function chatScopeKey(scope: ChatScope): string {
  return `${scope.sessionType}:${scope.analysisId ?? ""}`;
}
