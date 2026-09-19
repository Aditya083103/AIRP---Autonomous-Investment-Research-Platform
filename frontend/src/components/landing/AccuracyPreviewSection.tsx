// frontend/src/components/landing/AccuracyPreviewSection.tsx
// Landing page redesign -- a track-record section placed right after
// CommitteeSection: having just met the 8 agents, a reader's next
// question is naturally "okay, but has any of this actually been
// right?". Answers it with real numbers pulled from the same public
// GET /api/v1/accuracy/summary endpoint AccuracyPage.tsx itself uses
// (via the existing useAccuracySummary hook, same React Query pattern
// as every other data-driven landing tile in this codebase) -- never a
// static screenshot or a hardcoded literal.
//
// B7's "why this page might look empty" honesty (AccuracyPage.tsx) is
// repeated here in miniature: a verdict is only scored once its
// evaluation_horizon_days elapses, so a young or quiet deployment can
// legitimately have `overall_accuracy_pct === null` -- that state gets
// its own plain-language explanation, not a placeholder "--" left to
// speak for itself.
//
// Card hierarchy: the stat card is this section's own primary anchor
// (border, no shadow) -- see DemoCtaSection's own note on the same
// convention.

import { Link } from "react-router-dom";

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Reveal } from "@/components/motion/Reveal";
import { Card, Skeleton } from "@/components/ui";
import { useAccuracySummary } from "@/hooks/useAccuracySummary";
import { getDisplayErrorMessage } from "@/lib/apiErrorMessage";

const FALLBACK_ERROR_MESSAGE = "Could not load accuracy data right now.";

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatCount(value: number): string {
  return Math.round(value).toLocaleString("en-IN");
}

function CardBody(): JSX.Element {
  const { data: summary, isLoading, isError, error } = useAccuracySummary();

  if (isLoading) {
    return (
      <div className="space-y-3" role="status">
        <span className="sr-only">Loading accuracy data…</span>
        <Skeleton className="h-9 w-28" />
        <Skeleton className="h-4 w-48" />
      </div>
    );
  }

  if (isError || !summary) {
    return (
      <p role="alert" className="text-sm text-verdict-sell">
        {getDisplayErrorMessage(error, FALLBACK_ERROR_MESSAGE)}
      </p>
    );
  }

  if (summary.overall_accuracy_pct === null || summary.total_evaluated === 0) {
    return (
      <div>
        <p className="text-sm font-semibold text-ink">Not enough scored verdicts yet</p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          A verdict is only scored against the real market once its evaluation horizon elapses --
          e.g. a 3-month HOLD is checked roughly 3 months later. That is not a bug; the numbers here
          fill in automatically as evaluations complete.
          {summary.total_pending > 0
            ? ` ${formatCount(summary.total_pending)} verdict${summary.total_pending === 1 ? "" : "s"} ${summary.total_pending === 1 ? "is" : "are"} currently waiting on its scoring date.`
            : ""}
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-muted">Overall directional accuracy</p>
      <p className="mt-2 font-display text-4xl font-semibold text-ink">
        <AnimatedNumber value={summary.overall_accuracy_pct} format={formatPercent} />
      </p>
      <dl className="mt-5 flex gap-8 border-t border-line pt-4 text-sm">
        <div>
          <dt className="text-xs text-muted">Verdicts scored</dt>
          <dd className="mt-1 font-mono font-semibold text-ink">
            <AnimatedNumber value={summary.total_evaluated} format={formatCount} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Awaiting evaluation</dt>
          <dd className="mt-1 font-mono font-semibold text-ink">
            <AnimatedNumber value={summary.total_pending} format={formatCount} />
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** Track-record section: pulls live numbers from GET /api/v1/accuracy/summary. */
export function AccuracyPreviewSection(): JSX.Element {
  return (
    <section className="py-16" data-testid="accuracy-preview-section">
      <div className="grid gap-8 lg:grid-cols-[0.9fr,1.1fr] lg:items-center">
        <Reveal>
          <Card className="shadow-none" data-testid="accuracy-preview-card">
            <CardBody />
          </Card>
        </Reveal>

        <Reveal index={1}>
          <div>
            <h2 className="font-display text-3xl font-semibold text-ink">
              AIRP grades its own homework.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted">
              Every BUY/HOLD/SELL verdict is tracked against what the stock actually did after the
              call, using a real evaluation horizon -- not just how confident the memo sounded on
              the day it was written.
            </p>
            <Link
              to="/accuracy"
              className="mt-6 inline-flex h-11 items-center justify-center rounded-card border border-teal-500/50 px-5 text-sm font-medium text-teal-300 transition-colors hover:bg-teal-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
            >
              See the full accuracy dashboard
            </Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
