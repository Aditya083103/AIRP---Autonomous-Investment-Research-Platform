// frontend/src/hooks/useAccuracySummary.ts
// AIRP -- useAccuracySummary hook (T-092)
//
// React Query wrapper around GET /api/v1/accuracy/summary. No `enabled`
// gate and no accessToken parameter, unlike every other hook in this
// directory -- the endpoint is public (backend/routers/accuracy.py's
// module docstring) and needs no per-caller state to decide whether to
// fire, so this hook can simply run on mount the way useQuery's own
// defaults intend. Uses the shared queryClient defaults (30s staleTime)
// rather than overriding to Infinity the way useAnalysisResult.ts does --
// verdict_outcomes grows and gets scored continuously in the background
// (T-089's daily cron), so, like useAnalysisHistory.ts, this data is not
// immutable once fetched and should refetch on the shared client's
// normal cadence.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchAccuracySummary } from "@/api/accuracy";
import { type AccuracySummaryResponse } from "@/types/accuracy";

export function useAccuracySummary(): UseQueryResult<AccuracySummaryResponse> {
  return useQuery({
    queryKey: ["accuracy-summary"],
    queryFn: fetchAccuracySummary,
  });
}
