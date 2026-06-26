// frontend/src/components/AgentProgressDemo.tsx
//
// AIRP -- Live Agent Progress Demo Component (T-049)
//
// A minimal, self-contained component that proves the T-049 contract
// end-to-end on the frontend: connect to WS /api/v1/analysis/{job_id}/stream,
// receive AgentStreamEvent messages, and render them in arrival order.
//
// This is NOT the Phase 6 dashboard's real live-progress viewer (that is
// T-053 onward, with its own design system, layout, and data fetching via
// React Query per docs/ARCHITECTURE.md) -- it exists so T-049's "frontend
// receives and displays in order" acceptance criterion has a genuine,
// runnable frontend consumer today, rather than only a backend contract
// that nothing yet renders. Phase 6 can delete or replace this file
// outright once the real dashboard lands; useAnalysisStream
// (src/hooks/useAnalysisStream.ts) is the reusable part worth keeping.

import { useState } from "react";

import { useAnalysisStream } from "../hooks/useAnalysisStream";

interface AgentProgressDemoProps {
  /** UUID of the analysis job to stream, e.g. from POST /api/v1/analysis/start. */
  jobId: string;
  /** Bearer access token from POST /auth/login. */
  token: string;
}

/** Renders one AgentStreamEvent as a single progress-log row. */
function AgentEventRow({
  index,
  agent,
  status,
  outputPreview,
  progressPercent,
  isFinal,
}: {
  index: number;
  agent: string;
  status: string;
  outputPreview: string;
  progressPercent: number;
  isFinal: boolean;
}): JSX.Element {
  return (
    <li className="flex items-baseline gap-3 border-b border-slate-200 py-2 text-sm">
      <span className="w-6 shrink-0 text-right text-slate-400">{index + 1}.</span>
      <span className="w-40 shrink-0 font-mono font-semibold text-slate-700">{agent}</span>
      <span className="w-16 shrink-0 text-slate-500">{progressPercent}%</span>
      <span className="flex-1 text-slate-600">{outputPreview}</span>
      <span
        className={
          isFinal
            ? "shrink-0 rounded px-2 py-0.5 text-xs font-medium text-white " +
              (status === "failed" ? "bg-red-600" : "bg-emerald-600")
            : "shrink-0 rounded bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600"
        }
      >
        {status}
      </span>
    </li>
  );
}

/**
 * Demo viewer for WS /api/v1/analysis/{job_id}/stream.
 *
 * Lets a developer paste a job_id and an access token and watch real
 * AgentStreamEvent messages arrive and render in order -- the literal
 * acceptance criterion for T-049 -- without needing the rest of the
 * Phase 6 dashboard (auth pages, routing, the analysis-trigger form) to
 * exist first.
 */
export function AgentProgressDemo({ jobId, token }: AgentProgressDemoProps): JSX.Element {
  const [enabled, setEnabled] = useState(false);

  const { events, connectionStatus, isComplete, error } = useAnalysisStream({
    jobId,
    token,
    enabled,
  });

  return (
    <div className="mx-auto max-w-2xl rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-800">Live analysis progress</h2>
        <button
          type="button"
          onClick={(): void => setEnabled(true)}
          disabled={enabled}
          className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
        >
          {enabled ? "Streaming…" : "Connect"}
        </button>
      </div>

      <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">
        connection: {connectionStatus}
        {isComplete ? " · complete" : ""}
      </p>

      {error !== null && (
        <p className="mb-2 rounded bg-red-50 px-2 py-1 text-sm text-red-700">{error}</p>
      )}

      {events.length === 0 ? (
        <p className="text-sm text-slate-400">No events yet.</p>
      ) : (
        <ol className="divide-y divide-slate-100">
          {events.map((event, index) => (
            <AgentEventRow
              key={`${event.agent}-${index}`}
              index={index}
              agent={event.agent}
              status={event.status}
              outputPreview={event.output_preview}
              progressPercent={event.progress_percent}
              isFinal={event.is_final}
            />
          ))}
        </ol>
      )}
    </div>
  );
}

export default AgentProgressDemo;
