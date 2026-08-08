// frontend/src/hooks/useAccuracyHistory.ts
// AIRP -- useAccuracyHistory hook (T-092)
//
// React Query wrapper around GET /api/v1/accuracy/history. Same "no
// enabled gate, no accessToken" shape as useAccuracySummary.ts -- see
// that file's docstring for why. AccuracyPage.tsx (this task) is this
// hook's only caller today, fetching one large page
// (MAX_HISTORY_PAGE_SIZE_HINT, see below) to build the rolling accuracy
// trend line and the conviction-vs-accuracy scatter chart client-side,
// rather than paginating a visible table -- there is no accuracy
// history *table* in this UI yet, only the two charts derived from it.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchAccuracyHistory } from "@/api/accuracy";
import { type AccuracyHistoryResponse } from "@/types/accuracy";

/**
 * Mirrors backend.services.accuracy_tracker.MAX_ACCURACY_HISTORY_PAGE_SIZE.
 * AccuracyPage.tsx requests this many rows per page so its two
 * history-derived charts see as complete a picture as the API allows in
 * one request, rather than only the newest 20
 * (DEFAULT_ACCURACY_HISTORY_PAGE_SIZE) a caller gets by omitting `limit`.
 */
export const MAX_ACCURACY_HISTORY_PAGE_SIZE = 100;

export interface UseAccuracyHistoryParams {
  limit?: number;
  offset?: number;
}

export function useAccuracyHistory({
  limit = MAX_ACCURACY_HISTORY_PAGE_SIZE,
  offset = 0,
}: UseAccuracyHistoryParams = {}): UseQueryResult<AccuracyHistoryResponse> {
  return useQuery({
    queryKey: ["accuracy-history", limit, offset],
    queryFn: () => fetchAccuracyHistory({ limit, offset }),
  });
}
