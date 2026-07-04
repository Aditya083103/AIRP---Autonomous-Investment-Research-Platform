// frontend/src/hooks/useAnalysisCharts.ts
// AIRP -- useAnalysisCharts hook (T-062)
//
// React Query wrapper around GET /api/v1/analysis/{job_id}/charts,
// same shape as useAnalysisResult.ts (T-061) -- `staleTime: Infinity`
// because a completed analysis's chart data never changes once fetched
// (the two live yFinance calls the backend makes are a snapshot in
// time, and the three agent-output-derived sources are immutable once
// persisted), and `enabled` is left to the caller to compute from the
// live WebSocket stream, the same separation of concerns
// useAnalysisResult.ts keeps.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchAnalysisCharts } from "@/api/analysis";
import { type AnalysisChartDataResponse } from "@/types/analysis";

export interface UseAnalysisChartsParams {
  jobId: string;
  accessToken: string | null;
  /** Gate the query on the pipeline actually being done -- see this file's docstring. */
  enabled: boolean;
}

export function useAnalysisCharts({
  jobId,
  accessToken,
  enabled,
}: UseAnalysisChartsParams): UseQueryResult<AnalysisChartDataResponse> {
  return useQuery({
    queryKey: ["analysis-charts", jobId, accessToken],
    queryFn: () => fetchAnalysisCharts({ accessToken: accessToken as string, jobId }),
    enabled: enabled && accessToken !== null && jobId !== "",
    staleTime: Infinity,
  });
}
