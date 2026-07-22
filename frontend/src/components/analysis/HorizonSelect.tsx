// frontend/src/components/analysis/HorizonSelect.tsx
// AIRP -- Analysis Horizon selector (T-085)
//
// A labelled native <select> for choosing the OHLCV lookback window
// the Technical Analyst agent fetches -- "1mo" through "10y" (see
// src/lib/validation/analysisSchemas.ts's ANALYSIS_HORIZONS, which
// mirrors backend.tools.stock_price.VALID_PERIODS exactly).
//
// A plain native <select> (rather than a custom listbox, as
// CompanyAutocomplete uses for its ~50-item searchable list) is
// intentional here: seven fixed, short options is exactly the case
// the native control handles well -- full keyboard support, no
// positioning logic to write, and no accessibility work beyond the
// <label htmlFor> pairing every other field in this design system
// already uses (see Input.tsx).

import { forwardRef, useId, type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";
import { ANALYSIS_HORIZONS, ANALYSIS_HORIZON_LABELS } from "@/lib/validation/analysisSchemas";

export interface HorizonSelectProps
  extends Omit<ComponentPropsWithoutRef<"select">, "size" | "children"> {
  /** Visible label above the field. Required -- every field must be labelled. */
  label: string;
  /** Helper text shown below the field. */
  hint?: string;
}

/**
 * AIRP's Analysis Horizon selector. Defaults to "1y" via the parent
 * form's `defaultValues` (see AnalysisPage.tsx) -- this component
 * itself has no opinion on the selected value beyond rendering
 * whatever `value`/`onChange` react-hook-form's `register()` wires up.
 */
export const HorizonSelect = forwardRef<HTMLSelectElement, HorizonSelectProps>(
  function HorizonSelect({ label, hint, id, className, disabled, ...rest }, ref) {
    const generatedId = useId();
    const selectId = id ?? generatedId;
    const hintId = `${selectId}-hint`;

    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor={selectId} className="text-sm font-medium text-ink">
          {label}
        </label>

        <div
          className={cn(
            "flex h-10 items-center rounded-card border border-line bg-surface px-3",
            "transition-colors focus-within:ring-2 focus-within:ring-brand-500",
            "focus-within:ring-offset-2 focus-within:ring-offset-canvas",
            disabled && "cursor-not-allowed bg-canvas opacity-60",
          )}
        >
          <select
            ref={ref}
            id={selectId}
            disabled={disabled}
            aria-describedby={hint ? hintId : undefined}
            className={cn(
              "h-full w-full bg-transparent text-sm text-ink",
              "focus:outline-none disabled:cursor-not-allowed",
              className,
            )}
            {...rest}
          >
            {ANALYSIS_HORIZONS.map((horizon) => (
              <option key={horizon} value={horizon}>
                {ANALYSIS_HORIZON_LABELS[horizon]}
              </option>
            ))}
          </select>
        </div>

        {hint ? (
          <p id={hintId} className="text-xs text-muted">
            {hint}
          </p>
        ) : null}
      </div>
    );
  },
);
