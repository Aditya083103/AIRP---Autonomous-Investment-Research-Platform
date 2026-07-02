// frontend/src/components/dashboard/HistoryTable.tsx
// AIRP -- History table (T-057)
//
// Renders the columns the acceptance criterion asks for: company, date,
// verdict badge, and a score column. backend.models.schemas.
// HistoryEntryResponse has no separate "risk score" field -- only
// conviction_score (1-10, from the Portfolio Manager, see
// AIRP_Project_Overview_Updated.docx section 3) -- so this table labels
// that column "Conviction" rather than "Risk" and shows it honestly as
// what the API actually returns, instead of mislabelling it to match
// the task description's wording. A per-agent Risk Officer score exists
// only in the full GET /.../result payload (T-061's Results page), not
// in this lightweight history list.

import { Link } from "react-router-dom";

import { VerdictBadge } from "@/components/dashboard/VerdictBadge";
import { type HistoryEntryResponse } from "@/types/analysis";

interface HistoryTableProps {
  entries: readonly HistoryEntryResponse[];
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function HistoryTable({ entries }: HistoryTableProps): JSX.Element {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
            <th className="py-3 pr-4 font-medium">Company</th>
            <th className="py-3 pr-4 font-medium">Date</th>
            <th className="py-3 pr-4 font-medium">Verdict</th>
            <th className="py-3 pr-4 font-medium">Conviction</th>
            <th className="py-3 pr-0 font-medium">
              <span className="sr-only">Detail link</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.job_id} className="border-b border-line last:border-0">
              <td className="py-3 pr-4">
                <p className="font-medium text-ink">{entry.company_name}</p>
                <p className="font-mono text-xs text-muted">{entry.ticker}</p>
              </td>
              <td className="py-3 pr-4 text-muted">{formatDate(entry.requested_at)}</td>
              <td className="py-3 pr-4">
                <VerdictBadge verdict={entry.verdict} status={entry.status} />
              </td>
              <td className="py-3 pr-4 font-mono text-ink">
                {entry.conviction_score !== null ? `${entry.conviction_score}/10` : "—"}
              </td>
              <td className="py-3 pr-0 text-right">
                <Link
                  to={`/analysis/${entry.job_id}/result`}
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
