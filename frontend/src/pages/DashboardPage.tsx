// frontend/src/pages/DashboardPage.tsx
// AIRP -- Dashboard (T-057, loading/empty states refined in T-066)
//
// Replaces T-056's placeholder with the real page: the user's analysis
// history loaded from GET /api/v1/analysis/history via
// useAnalysisHistory (React Query), a company-name search box, and a
// verdict-badged table (HistoryTable) with a link to each row's detail
// page.
//
// Search is client-side, over the currently loaded page only --
// backend.routers.analysis's history endpoint takes limit/offset, not a
// text filter, and adding a `company_name` query param there means
// changing backend.services.analysis's raw SQL
// (_SQL_LOAD_HISTORY_PAGE/_SQL_COUNT_HISTORY) without being able to run
// the backend test suite to verify it -- the same reasoning
// backend/routers/auth.py's T-056 docstring already applied to why
// get_current_user was left untouched. A caption under the search box
// says so explicitly rather than implying it searches everything.
//
// T-066 replaces the plain spinner+text loading row with
// HistoryTableSkeleton (shaped like the real table, so there's no
// layout jump once it loads) and both zero-result branches with
// <EmptyState> -- "no history at all" now includes a CTA straight to
// /analysis, since that is the one thing a person seeing this page for
// the first time actually needs to do next. The failed-fetch branch is
// unchanged (still inline red text): src/lib/queryClient.ts's global
// onError already puts the same message in a toast automatically, so
// this inline text is the *persistent* detail for someone who missed
// the toast, not a duplicate of it.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { HistoryTable } from "@/components/dashboard/HistoryTable";
import { HistoryTableSkeleton } from "@/components/skeletons";
import { Button, EmptyState, Input } from "@/components/ui";
import { useAnalysisHistory } from "@/hooks/useAnalysisHistory";
import { useAuth } from "@/hooks/useAuth";

const PAGE_SIZE = 20;

export function DashboardPage(): JSX.Element {
  const { user, accessToken } = useAuth();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");

  const { data, isLoading, isError, error, isFetching } = useAnalysisHistory({
    accessToken,
    limit: PAGE_SIZE,
    offset,
  });

  const filteredItems = useMemo(() => {
    if (!data) {
      return [];
    }
    const query = search.trim().toLowerCase();
    if (query.length === 0) {
      return data.items;
    }
    return data.items.filter((entry) => entry.company_name.toLowerCase().includes(query));
  }, [data, search]);

  return (
    <div>
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Dashboard</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        Welcome back, {user?.display_name ?? user?.email}.
      </h1>
      <p className="mt-2 text-sm text-muted">Your past analyses, newest first.</p>

      <div className="mt-8 max-w-xs">
        <Input
          label="Search by company"
          placeholder="e.g. Infosys"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          hint="Searches the analyses currently loaded on this page."
        />
      </div>

      <div className="mt-6">
        {isLoading ? (
          <HistoryTableSkeleton label="Loading your analysis history…" />
        ) : isError ? (
          <p role="alert" className="py-12 text-sm text-verdict-sell">
            {error instanceof Error ? error.message : "Could not load your analysis history."}
          </p>
        ) : data && data.items.length === 0 ? (
          <EmptyState
            title="You haven't run an analysis yet."
            description="Start one from the analysis page to see it here."
            action={
              <Link
                to="/analysis"
                className="text-sm font-medium text-brand-600 hover:text-brand-700"
              >
                Run an analysis →
              </Link>
            }
          />
        ) : filteredItems.length === 0 ? (
          <EmptyState title={`No loaded analyses match "${search}".`} />
        ) : (
          <>
            <HistoryTable entries={filteredItems} />
            <div className="mt-4 flex items-center justify-between text-sm text-muted">
              <span>
                {data ? `${data.total_count} total analyses` : null}
                {isFetching ? " · refreshing…" : null}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!data?.has_more}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
