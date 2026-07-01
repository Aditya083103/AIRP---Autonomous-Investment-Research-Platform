// frontend/src/components/ui/Input.tsx
// Design-system primitive (T-054). A labelled text input wired for
// react-hook-form (forwardRef so RHF's `register()` can attach its ref
// directly) and for accessible error reporting: the error message is
// linked to the input via aria-describedby and aria-invalid is set
// whenever an error is present, so screen readers announce it correctly.

import { forwardRef, useId, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface InputProps extends Omit<ComponentPropsWithoutRef<"input">, "size"> {
  /** Visible label above the field. Required — every field must be labelled. */
  label: string;
  /** Validation/error message. When present, the input is styled as invalid. */
  error?: string;
  /** Helper text shown below the field when there is no error. */
  hint?: string;
  /** Visually hides the label while keeping it in the accessibility tree. */
  hideLabel?: boolean;
  /** Optional node rendered inside the field, before the text (e.g. a currency symbol). */
  leadingAddon?: ReactNode;
  /** Optional node rendered inside the field, after the text (e.g. a unit). */
  trailingAddon?: ReactNode;
}

/**
 * AIRP's base text input. Used for the company-name search box, auth forms,
 * and any other free-text or numeric field in the app.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    error,
    hint,
    hideLabel = false,
    leadingAddon,
    trailingAddon,
    id,
    className,
    disabled,
    ...rest
  },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const describedBy = error ? errorId : hint ? hintId : undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={inputId}
        className={cn("text-sm font-medium text-ink", hideLabel && "sr-only")}
      >
        {label}
      </label>

      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-card border bg-surface px-3 transition-colors",
          "focus-within:ring-2 focus-within:ring-brand-500 focus-within:ring-offset-2",
          "focus-within:ring-offset-canvas",
          error ? "border-verdict-sell" : "border-line",
          disabled && "cursor-not-allowed bg-canvas opacity-60",
        )}
      >
        {leadingAddon && <span className="shrink-0 text-muted">{leadingAddon}</span>}
        <input
          ref={ref}
          id={inputId}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          className={cn(
            "h-full w-full bg-transparent text-sm text-ink placeholder:text-muted",
            "focus:outline-none disabled:cursor-not-allowed",
            className,
          )}
          {...rest}
        />
        {trailingAddon && <span className="shrink-0 text-muted">{trailingAddon}</span>}
      </div>

      {error ? (
        <p id={errorId} role="alert" className="text-xs text-verdict-sell">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
