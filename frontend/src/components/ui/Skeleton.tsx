// frontend/src/components/ui/Skeleton.tsx
// Design-system primitive (T-066). A single pulsing placeholder bar --
// the building block every composed skeleton in src/components/skeletons/
// (HistoryTableSkeleton, ResultsPanelSkeleton, ChartsPanelSkeleton) is
// assembled from, the same way those pages already assemble their real
// content from Card/Badge/Spinner rather than one another hand-rolling
// markup. Purely visual and `aria-hidden` on every individual bar --
// the *composition* that groups several bars together is what carries
// the accessible loading announcement (`role="status"` + a visually-
// hidden label), mirroring Spinner.tsx's own decorative-vs-announced
// split. A screen reader should hear "Loading your analysis history…"
// once, not eleven identical "loading" announcements for eleven bars.

import { type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";

export type SkeletonProps = ComponentPropsWithoutRef<"div">;

/** A pulsing placeholder bar. Size/shape controlled via `className` (e.g. `h-4 w-32`). */
export function Skeleton({ className, ...rest }: SkeletonProps): JSX.Element {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-line", className)}
      {...rest}
    />
  );
}
