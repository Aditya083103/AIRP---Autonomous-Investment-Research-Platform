// frontend/src/components/ui/Badge.tsx
// Design-system primitive (T-054). A small status pill used throughout
// the dashboard and memo views: agent status ("running", "done", "failed"),
// risk flags, and -- most importantly -- the BUY/HOLD/SELL verdict chip
// that is AIRP's signature visual element (see HomePage.tsx's VERDICTS).

import { type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";

export type BadgeTone = "neutral" | "brand" | "buy" | "hold" | "sell";

export interface BadgeProps extends ComponentPropsWithoutRef<"span"> {
  /** Colour treatment. Defaults to "neutral". Use "buy"/"hold"/"sell" for verdicts. */
  tone?: BadgeTone;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-canvas text-muted",
  brand: "bg-brand-50 text-brand-700",
  buy: "bg-verdict-buy text-white",
  hold: "bg-verdict-hold text-white",
  sell: "bg-verdict-sell text-white",
};

/** A compact, rounded label for status, category, or verdict display. */
export function Badge({ tone = "neutral", className, children, ...rest }: BadgeProps): JSX.Element {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-xs font-semibold",
        TONE_CLASSES[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
