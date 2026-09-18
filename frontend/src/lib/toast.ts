// frontend/src/lib/toast.ts
// AIRP -- toast() convenience API (T-066)
//
// The call-site-friendly surface over toastStore.ts's bare `.add()` --
// every page/hook in this app that wants to show a toast writes
// `toast.error("...")` rather than `toastStore.add("error", "...")`,
// the same "small ergonomic wrapper over a primitive store" shape
// src/lib/queryClient.ts already is for TanStack Query itself.

import { getDisplayErrorMessage } from "@/lib/apiErrorMessage";
import { toastStore } from "@/lib/toastStore";

export const toast = {
  success: (message: string): string => toastStore.add("success", message),
  error: (message: string): string => toastStore.add("error", message),
  info: (message: string): string => toastStore.add("info", message),
};

const GENERIC_API_ERROR_MESSAGE = "Something went wrong. Please try again.";

/**
 * Extracts a human-readable message from a caught API error and shows
 * it as an error toast.
 *
 * `AnalysisApiError` and `AuthApiError` (src/api/analysis.ts,
 * src/api/auth.ts) both already carry a human-readable `.message` --
 * anything else caught here (a network failure, a thrown non-Error
 * value) falls back to a generic message rather than surfacing
 * `undefined` or a raw stack trace to the user. A raw fetch()-level
 * network failure (the backend waking up from a Render free-tier cold
 * start, mid-fetch) is also an `Error`, but its literal browser message
 * ("Failed to fetch") is not something a user can act on -- see
 * src/lib/apiErrorMessage.ts's own docstring -- so that case is rewritten
 * to a friendlier explanation before anything else here. This is the one
 * helper every manual `catch` block in the app (LoginPage, RegisterPage,
 * AnalysisPage, ComparePage) calls, so the "what counts as a
 * displayable error message" rule lives in exactly one place;
 * src/lib/queryClient.ts's automatic query/mutation-failure toasts use
 * the same fallback message for anything that isn't an `Error`.
 */
export function toastApiError(error: unknown): void {
  toast.error(getDisplayErrorMessage(error, GENERIC_API_ERROR_MESSAGE));
}

export { GENERIC_API_ERROR_MESSAGE };
