// frontend/src/components/ui/EmptyState.tsx
// Design-system primitive (T-066). A consistent "there's nothing here
// yet" visual -- a short title, optional supporting copy, and an
// optional call-to-action -- used anywhere a successful, non-error
// fetch legitimately returns zero items (DashboardPage's "no analyses
// yet" and "no search matches" branches are the first two consumers).
// Deliberately distinct from an error state: an empty state is not a
// failure, so it never uses verdict-sell red or `role="alert"` -- it's
// centred, muted-toned, and reads as "act here next", not "something
// broke".

import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** e.g. a Link or Button pointing at the obvious next action. */
  action?: ReactNode;
  className?: string;
}

/** Centred "nothing here yet" placeholder: title, optional description, optional CTA. */
export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps): JSX.Element {
  return (
    <div
      className={cn("flex flex-col items-center gap-2 py-12 text-center", className)}
      data-testid="empty-state"
    >
      <p className="text-sm font-medium text-ink">{title}</p>
      {description ? <p className="max-w-sm text-sm text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
