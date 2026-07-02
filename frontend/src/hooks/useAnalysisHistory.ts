// frontend/src/hooks/useAnalysisHistory.ts
// AIRP -- useAnalysisHistory hook (T-057)
//
// React Query wrapper around GET /api/v1/analysis/history, per
// docs/ARCHITECTURE.md's stated intent for src/lib/queryClient.ts (its
// own docstring calls out "analysis status, results, history" as the
// data this client's defaults are tuned for). `enabled` gates the
// query on having a real access token -- DashboardPage is already
// wrapped in ProtectedRoute, so accessToken should never be null in
// practice, but the hook stays honest about the type either way rather
// than asserting it non-null at the call site.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchAnalysisHistory } from "@/api/analysis";
import { type HistoryResponse } from "@/types/analysis";

export interface UseAnalysisHistoryParams {
  accessToken: string | null;
  limit: number;
  offset: number;
}

export function useAnalysisHistory({
  accessToken,
  limit,
  offset,
}: UseAnalysisHistoryParams): UseQueryResult<HistoryResponse> {
  return useQuery({
    queryKey: ["analysis-history", accessToken, limit, offset],
    queryFn: () => fetchAnalysisHistory({ accessToken: accessToken as string, limit, offset }),
    enabled: accessToken !== null,
  });
}
