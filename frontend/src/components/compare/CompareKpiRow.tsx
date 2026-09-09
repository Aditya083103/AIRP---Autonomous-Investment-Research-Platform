// frontend/src/components/compare/CompareKpiRow.tsx
// AIRP -- Compare KPI card row (B11)
//
// Five glanceable cards above the full ComparisonTable: verdict,
// conviction, P/E valuation gap, risk score, and sentiment, each side by
// side for the two companies being compared. Built from
// src/lib/compare/compareKpis.ts's buildCompareKpis, which is the only
// place that reads the raw decision/charts payloads -- this component's
// job is purely display, the same "computation separate from
// rendering" split every other B7/B11 chart/lib pair in this codebase
// already follows.

import { Reveal } from "@/components/motion/Reveal";
import { TiltCard } from "@/components/three/TiltCard";
import { Badge, Card } from "@/components/ui";
import { buildCompareKpis } from "@/lib/compare/compareKpis";
import { type CompanySide } from "@/lib/compare/winnerLogic";
import { type Verdict } from "@/types/analysis";

export interface CompareKpiRowProps {
  companyNameA: string;
  companyNameB: string;
  sideA: CompanySide;
  sideB: CompanySide;
}

const VERDICT_TONE: Record<Verdict, "buy" | "hold" | "sell"> = {
  BUY: "buy",
  HOLD: "hold",
  SELL: "sell",
};

function isVerdict(value: string): value is Verdict {
  return value === "BUY" || value === "HOLD" || value === "SELL";
}

function KpiValue({ value }: { value: string }): JSX.Element {
  if (isVerdict(value)) {
    return <Badge tone={VERDICT_TONE[value]}>{value}</Badge>;
  }
  return <span className="font-mono text-lg font-semibold text-ink">{value}</span>;
}

/** Five headline KPI cards comparing both companies at a glance, above the full metric table. */
export function CompareKpiRow({
  companyNameA,
  companyNameB,
  sideA,
  sideB,
}: CompareKpiRowProps): JSX.Element {
  const kpis = buildCompareKpis(sideA, sideB);

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5" data-testid="compare-kpi-row">
      {kpis.map((kpi, index) => (
        <Reveal key={kpi.id} index={index}>
          <TiltCard>
            <Card>
              <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">
                {kpi.label}
              </p>
              <div className="mt-3 flex items-center justify-between gap-2">
                <div>
                  <p className="truncate text-[10px] uppercase text-muted">{companyNameA}</p>
                  <KpiValue value={kpi.valueA} />
                </div>
                <div className="text-right">
                  <p className="truncate text-[10px] uppercase text-muted">{companyNameB}</p>
                  <KpiValue value={kpi.valueB} />
                </div>
              </div>
              {kpi.note ? <p className="mt-2 text-xs text-muted">{kpi.note}</p> : null}
            </Card>
          </TiltCard>
        </Reveal>
      ))}
    </div>
  );
}
