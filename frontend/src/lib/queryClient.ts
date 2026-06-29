// frontend/src/lib/queryClient.ts
// The single shared React Query client for the app. Defaults are tuned for
// AIRP's read-mostly data (analysis status, results, history): a short
// staleTime avoids hammering the backend during live polling, retries are
// kept low so genuine 4xx errors surface fast, and refetch-on-focus is off
// because analysis results are immutable once complete.

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
