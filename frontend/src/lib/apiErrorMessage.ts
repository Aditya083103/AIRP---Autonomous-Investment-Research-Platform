// frontend/src/lib/apiErrorMessage.ts
// AIRP -- shared "is this a raw network failure?" + friendly-message helper.
//
// Root cause this exists for: the backend (Render free tier) spins its
// container down after ~15 minutes idle and takes 30-60s to wake on the
// next request. During that window `fetch()` itself rejects with a raw
// browser TypeError ("Failed to fetch" in Chrome, "NetworkError when
// attempting to fetch resource" in Firefox, "Load failed" in Safari) --
// this never reaches AccuracyApiError/AnalysisApiError's own
// response-based error handling, because no response ever arrives.
// Every call site that does `error instanceof Error ? error.message : ...`
// (src/lib/toast.ts's toastApiError, AccuracyPage.tsx, DashboardPage.tsx)
// was therefore showing that raw string verbatim to real users. This
// module is the one place that recognises that class of error and
// rewrites it into something a non-technical user can act on.

const NETWORK_ERROR_MESSAGE =
  "Could not reach the server. It may be waking up from idle -- please try again in a few seconds.";

// Exact browser-native fetch()-rejection messages across engines; matched
// case-insensitively as substrings since some environments prefix/suffix them.
const _NETWORK_ERROR_MESSAGE_PATTERNS = [
  "failed to fetch",
  "networkerror when attempting to fetch resource",
  "load failed",
  "network request failed",
];

/** True for a raw fetch()-level network failure (no HTTP response was ever received). */
export function isNetworkError(error: unknown): boolean {
  if (!(error instanceof TypeError)) {
    return false;
  }
  const message = error.message.toLowerCase();
  return _NETWORK_ERROR_MESSAGE_PATTERNS.some((pattern) => message.includes(pattern));
}

/**
 * Resolves a caught API error to a message safe to show a user: the
 * friendly cold-start explanation for a raw network failure, the error's
 * own message for anything else that is an `Error` (AccuracyApiError,
 * AnalysisApiError, AuthApiError already carry human-readable messages),
 * or `fallback` for a non-Error throw.
 */
export function getDisplayErrorMessage(error: unknown, fallback: string): string {
  if (isNetworkError(error)) {
    return NETWORK_ERROR_MESSAGE;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

export { NETWORK_ERROR_MESSAGE };
