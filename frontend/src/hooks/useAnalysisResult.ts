// frontend/src/hooks/useAnalysisResult.ts
// AIRP -- useAnalysisResult hook (T-061)
//
// React Query wrapper around GET /api/v1/analysis/{job_id}/result, the
// same shared client src/lib/queryClient.ts already tunes for
// "analysis status, results, history". `staleTime: Infinity` on top of
// that shared default is deliberate here (not just inherited) --
// backend.routers.analysis's own docstring for this endpoint says the
// InvestmentDecision it returns is immutable once status='completed',
// so unlike history (which can grow) or status (which changes while
// running), a successfully-fetched result never needs a background
// refetch for the lifetime of the query cache entry.
//
// `enabled` is the caller's responsibility to compute from the live
// WebSocket stream (useAnalysisStream) -- this hook does not know
// about is_final or hasFailed itself, the same separation of concerns
// useAnalysisHistory.ts keeps from AuthProvider.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchAnalysisResult } from "@/api/analysis";
import { type InvestmentDecisionResponse } from "@/types/analysis";

export interface UseAnalysisResultParams {
  jobId: string;
  accessToken: string | null;
  /** Gate the query on the pipeline actually being done -- see this file's docstring. */
  enabled: boolean;
}

export function useAnalysisResult({
  jobId,
  accessToken,
  enabled,
}: UseAnalysisResultParams): UseQueryResult<InvestmentDecisionResponse> {
  return useQuery({
    queryKey: ["analysis-result", jobId, accessToken],
    queryFn: () => fetchAnalysisResult({ accessToken: accessToken as string, jobId }),
    enabled: enabled && accessToken !== null && jobId !== "",
    staleTime: Infinity,
  });
}
