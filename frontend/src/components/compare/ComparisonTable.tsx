// frontend/src/components/compare/ComparisonTable.tsx
// AIRP -- Comparison table (T-064)
//
// A plain semantic <table>, not a Recharts/grid layout -- a
// metric-by-metric comparison is inherently tabular data, and every
// row already has a natural pair of cells (company A, company B) that
// a <table> renders correctly for free (row/column headers, screen
// reader navigation) without reimplementing that with divs.
//
// Winner highlighting: the winning cell for a row gets a green left
// border, a subtle tinted background, and a "Winner" badge -- ties and
// rows with no declared winner (see winnerLogic.ts's docstring on
// missing data) render both cells identically, so "no winner" is never
// visually confused with "company A won by a hair."

import { Badge, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { type ComparisonRow, type MetricWinner } from "@/lib/compare/winnerLogic";

export interface ComparisonTableProps {
  companyNameA: string;
  companyNameB: string;
  rows: ComparisonRow[];
}

function cellClasses(isWinner: boolean): string {
  return cn(
    "px-4 py-3 text-sm",
    isWinner ? "border-l-2 border-verdict-buy bg-verdict-buy/5 font-semibold text-ink" : "text-ink",
  );
}

function isCellWinner(winner: MetricWinner, side: "a" | "b"): boolean {
  return winner === side;
}

/** Renders every ComparisonRow as a table, highlighting the winning cell per metric. */
export function ComparisonTable({
  companyNameA,
  companyNameB,
  rows,
}: ComparisonTableProps): JSX.Element {
  return (
    <Card noPadding data-testid="comparison-table">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="px-4 py-3 text-xs font-medium uppercase text-muted">
                Metric
              </th>
              <th scope="col" className="px-4 py-3 text-sm font-semibold text-ink">
                {companyNameA}
              </th>
              <th scope="col" className="px-4 py-3 text-sm font-semibold text-ink">
                {companyNameB}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const winnerA = isCellWinner(row.winner, "a");
              const winnerB = isCellWinner(row.winner, "b");
              return (
                <tr key={row.id} className="border-b border-line last:border-0">
                  <th scope="row" className="px-4 py-3 text-sm font-medium text-muted">
                    {row.label}
                  </th>
                  <td className={cellClasses(winnerA)} data-testid={`cell-${row.id}-a`}>
                    <span className="flex items-center gap-2">
                      {row.displayA}
                      {winnerA ? (
                        <Badge tone="buy" className="text-[10px]">
                          Winner
                        </Badge>
                      ) : null}
                    </span>
                  </td>
                  <td className={cellClasses(winnerB)} data-testid={`cell-${row.id}-b`}>
                    <span className="flex items-center gap-2">
                      {row.displayB}
                      {winnerB ? (
                        <Badge tone="buy" className="text-[10px]">
                          Winner
                        </Badge>
                      ) : null}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
