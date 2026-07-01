// frontend/src/components/ui/Spinner.tsx
// Design-system primitive (T-054). A minimal animated loading indicator
// used inside Button (isLoading), on the live agent-progress dashboard,
// and anywhere else AIRP needs to signal "work in progress" without
// pulling in a charting/animation library for a single spinning ring.

import { type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";

export type SpinnerSize = "sm" | "md" | "lg";

export interface SpinnerProps extends ComponentPropsWithoutRef<"svg"> {
  /** Diameter of the spinner. Defaults to "md". */
  size?: SpinnerSize;
  /** Visually-hidden text for screen readers. Defaults to "Loading". */
  label?: string;
}

const SIZE_CLASSES: Record<SpinnerSize, string> = {
  sm: "h-4 w-4",
  md: "h-6 w-6",
  lg: "h-10 w-10",
};

/** A circular indeterminate progress indicator. Spins via CSS animation. */
export function Spinner({
  size = "md",
  label = "Loading",
  className,
  "aria-hidden": ariaHidden,
  ...rest
}: SpinnerProps): JSX.Element {
  const isDecorative = ariaHidden === true || ariaHidden === "true";

  return (
    <span className="inline-flex items-center" role={isDecorative ? undefined : "status"}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden={isDecorative ? "true" : undefined}
        className={cn("animate-spin text-current", SIZE_CLASSES[size], className)}
        {...rest}
      >
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="3"
          className="opacity-25"
        />
        <path
          d="M22 12a10 10 0 0 0-10-10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          className="opacity-90"
        />
      </svg>
      {!isDecorative && <span className="sr-only">{label}</span>}
    </span>
  );
}
