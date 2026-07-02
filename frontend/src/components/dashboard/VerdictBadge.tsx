// frontend/src/components/dashboard/VerdictBadge.tsx
// AIRP -- Verdict badge for the history table (T-057)
//
// backend.models.schemas.HistoryEntryResponse's `verdict` is null for
// any analysis that hasn't finished (or failed before producing a
// decision) -- Badge's existing buy/hold/sell tones (T-054) only cover
// the three real verdicts, so this wraps Badge with the extra
// pending/failed cases the dashboard actually has to render for a
// realistic history list, rather than assuming every row has a verdict.

import { Badge } from "@/components/ui";
import { type AnalysisStatus, type Verdict } from "@/types/analysis";

interface VerdictBadgeProps {
  verdict: Verdict | null;
  status: AnalysisStatus;
}

export function VerdictBadge({ verdict, status }: VerdictBadgeProps): JSX.Element {
  if (verdict === "BUY") {
    return <Badge tone="buy">BUY</Badge>;
  }
  if (verdict === "HOLD") {
    return <Badge tone="hold">HOLD</Badge>;
  }
  if (verdict === "SELL") {
    return <Badge tone="sell">SELL</Badge>;
  }
  if (status === "failed") {
    return <Badge tone="neutral">Failed</Badge>;
  }
  if (status === "running") {
    return <Badge tone="brand">Running</Badge>;
  }
  return <Badge tone="neutral">Pending</Badge>;
}
