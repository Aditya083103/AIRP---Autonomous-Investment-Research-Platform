// frontend/src/components/dashboard/DashboardKpiRow.tsx
// AIRP -- Dashboard KPI card row (B11)
//
// A 3-tile at-a-glance summary above HistoryTable: total analyses run
// (exact, from GET /api/v1/analysis/history's total_count), how many of
// this page's items have completed, and the account's most recent
// decided verdict. Built from src/lib/dashboard/dashboardKpis.ts's
// buildDashboardKpis, which is the only place that reads the raw
// HistoryEntryResponse rows -- this component's job is purely display,
// the same "computation separate from rendering" split every other
// B7/B11 KPI card in this codebase already follows.
//
// DashboardPage.tsx only renders this on the first page (offset === 0)
// -- see that file's own reasoning for why "most recent verdict" is
// only meaningful there.

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Reveal } from "@/components/motion/Reveal";
import { TiltCard } from "@/components/three/TiltCard";
import { Badge, Card } from "@/components/ui";
import { buildDashboardKpis } from "@/lib/dashboard/dashboardKpis";
import { type HistoryEntryResponse, type Verdict } from "@/types/analysis";

export interface DashboardKpiRowProps {
  items: HistoryEntryResponse[];
  totalCount: number;
}

const VERDICT_TONE: Record<Verdict, "buy" | "hold" | "sell"> = {
  BUY: "buy",
  HOLD: "hold",
  SELL: "sell",
};

/** Renders the Dashboard's 3-tile KPI row: total analyses, completed on this page, latest verdict. */
export function DashboardKpiRow({ items, totalCount }: DashboardKpiRowProps): JSX.Element {
  const kpis = buildDashboardKpis(items, totalCount);

  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="dashboard-kpi-row">
      <Reveal index={0}>
        <TiltCard>
          <Card>
            <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">
              Total analyses
            </p>
            <p className="mt-2 font-display text-3xl font-semibold text-ink">
              <AnimatedNumber value={kpis.totalAnalyses} />
            </p>
          </Card>
        </TiltCard>
      </Reveal>

      <Reveal index={1}>
        <TiltCard>
          <Card>
            <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">
              Completed (this page)
            </p>
            <p className="mt-2 font-display text-3xl font-semibold text-ink">
              <AnimatedNumber value={kpis.completedOnPage} />
            </p>
          </Card>
        </TiltCard>
      </Reveal>

      <Reveal index={2}>
        <TiltCard>
          <Card>
            <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">
              Most recent verdict
            </p>
            {kpis.mostRecentDecided ? (
              <div className="mt-2 flex items-center gap-2">
                <Badge tone={VERDICT_TONE[kpis.mostRecentDecided.verdict]}>
                  {kpis.mostRecentDecided.verdict}
                </Badge>
                <span className="truncate text-sm font-medium text-ink">
                  {kpis.mostRecentDecided.companyName}
                </span>
              </div>
            ) : (
              <p className="mt-2 font-display text-3xl font-semibold text-ink">--</p>
            )}
          </Card>
        </TiltCard>
      </Reveal>
    </div>
  );
}
