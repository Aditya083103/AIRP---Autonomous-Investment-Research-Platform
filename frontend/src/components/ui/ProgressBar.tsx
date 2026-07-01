// frontend/src/components/ui/ProgressBar.tsx
// Design-system primitive (T-054). A determinate progress indicator for
// the live agent-progress dashboard (each of the 8 agents reports a
// progress_percent over the WebSocket stream -- see useAnalysisStream.ts)
// and for any other "N% complete" display, e.g. document upload progress.

import { type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";

export interface ProgressBarProps extends ComponentPropsWithoutRef<"div"> {
  /** Current progress, 0-100. Values outside this range are clamped. */
  value: number;
  /** Optional label rendered above the bar, e.g. an agent name. */
  label?: string;
  /** Shows the numeric percentage next to the label. Defaults to true. */
  showValue?: boolean;
}

/** A horizontal, determinate progress bar with optional label and percentage. */
export function ProgressBar({
  value,
  label,
  showValue = true,
  className,
  ...rest
}: ProgressBarProps): JSX.Element {
  const clamped = Math.min(100, Math.max(0, value));

  return (
    <div className={cn("w-full", className)} {...rest}>
      {(label || showValue) && (
        <div className="mb-1.5 flex items-center justify-between text-xs">
          {label && <span className="font-medium text-ink">{label}</span>}
          {showValue && <span className="font-mono text-muted">{Math.round(clamped)}%</span>}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progress"}
        className="h-2 w-full overflow-hidden rounded-full bg-line"
      >
        <div
          className="h-full rounded-full bg-brand-600 transition-[width] duration-300 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
