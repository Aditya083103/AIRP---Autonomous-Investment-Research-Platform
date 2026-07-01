// frontend/src/components/ui/Button.tsx
// Design-system primitive (T-054). A single typed Button covering every
// interactive-action case the product needs: primary calls-to-action,
// secondary/ghost chrome actions, and a destructive variant for things
// like "delete analysis". Built on top of the native <button> element so
// every standard HTML button attribute (type, onClick, disabled, ...) is
// available for free via ComponentPropsWithoutRef.

import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ComponentPropsWithoutRef<"button"> {
  /** Visual treatment. Defaults to "primary". */
  variant?: ButtonVariant;
  /** Controls height, padding, and font size. Defaults to "md". */
  size?: ButtonSize;
  /** When true, shows a spinner in place of the leading icon and disables the button. */
  isLoading?: boolean;
  /** Optional icon (or any node) rendered before the label. Hidden while loading. */
  leadingIcon?: ReactNode;
  /** Optional icon (or any node) rendered after the label. Hidden while loading. */
  trailingIcon?: ReactNode;
  /** Stretches the button to fill its container's width. */
  fullWidth?: boolean;
}

const BASE_CLASSES =
  "inline-flex items-center justify-center gap-2 rounded-card font-medium " +
  "transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800",
  secondary: "border border-line bg-surface text-ink hover:bg-canvas active:bg-line",
  ghost: "bg-transparent text-ink hover:bg-canvas active:bg-line",
  danger: "bg-verdict-sell text-white hover:bg-red-700 active:bg-red-800",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

const SPINNER_SIZE: Record<ButtonSize, "sm" | "md"> = {
  sm: "sm",
  md: "sm",
  lg: "md",
};

/**
 * AIRP's base action button. Use `variant="danger"` for destructive actions
 * (e.g. deleting a saved analysis) and `isLoading` while an async action
 * (e.g. POST /api/v1/analysis/start) is in flight.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    isLoading = false,
    leadingIcon,
    trailingIcon,
    fullWidth = false,
    disabled,
    className,
    children,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      className={cn(
        BASE_CLASSES,
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        fullWidth && "w-full",
        className,
      )}
      {...rest}
    >
      {isLoading ? <Spinner size={SPINNER_SIZE[size]} aria-hidden="true" /> : leadingIcon}
      {children}
      {!isLoading && trailingIcon}
    </button>
  );
});
