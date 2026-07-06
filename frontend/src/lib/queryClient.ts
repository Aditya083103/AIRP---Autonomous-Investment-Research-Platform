// frontend/src/lib/queryClient.ts
// The single shared React Query client for the app. Defaults are tuned for
// AIRP's read-mostly data (analysis status, results, history): a short
// staleTime avoids hammering the backend during live polling, retries are
// kept low so genuine 4xx errors surface fast, and refetch-on-focus is off
// because analysis results are immutable once complete.
//
// T-066 adds a QueryCache/MutationCache pair with a shared `onError`: this
// is the mechanism behind "every API error shows a toast" holding for every
// current *and future* query/mutation in the app without each one needing
// its own toast call. TanStack Query calls `QueryCache.onError` only once a
// query has exhausted its retries and settled into an error state (not on
// every individual retry attempt), so a query that fails twice and then
// succeeds on its final retry never toasts at all -- this only fires for a
// genuine, final failure. `MutationCache.onError` fires once per failed
// mutation call, which is exactly the granularity a user-triggered action
// (e.g. useDownloadMemoPdf) needs.
//
// Hooks/pages that also show their own inline error UI (e.g.
// DashboardPage's isError branch, ResultsPanelSkeleton's replacement) are
// not fighting with this -- the toast is a transient, ambient notification
// that disappears after a few seconds; the inline UI is the persistent,
// contextual detail that stays on screen until the user acts. Both firing
// for the same failure is the same layering most production apps use, not
// a duplicate.

import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { toastApiError } from "@/lib/toast";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    onError: (error) => toastApiError(error),
  }),
  mutationCache: new MutationCache({
    onError: (error) => toastApiError(error),
  }),
});
