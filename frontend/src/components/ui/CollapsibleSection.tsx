// frontend/src/components/ui/CollapsibleSection.tsx
// Design-system primitive (T-063). A titled Card whose body can be
// toggled open/closed by clicking its header -- built for the
// Investment Memo page, where every section (executive summary,
// thesis, bull/bear case, risks, valuation, ...) needs to collapse so
// a reader can scan the memo's structure before diving into any one
// section's prose. Defaults to open: the memo should render fully
// expanded on first load (matching how MemoSection.tsx has always
// behaved), with collapsing an explicit, opt-in reader action rather
// than content hiding itself unless clicked.
//
// Deliberately keeps the collapsed subtree mounted (`hidden` attribute)
// rather than unmounting it -- a memo section's content is plain
// server-provided prose with no internal state to preserve, but
// `hidden` still keeps this component trivial to test (content stays
// queryable via `{ hidden: true }` in Testing Library) and avoids any
// remount flash if a reader toggles a section repeatedly.

import { useId, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface CollapsibleSectionProps {
  /** Section heading, shown in the always-visible header row. */
  title: ReactNode;
  /** Optional content shown next to the title (e.g. a badge or count). */
  headerExtra?: ReactNode;
  /** The section body, hidden when collapsed. */
  children: ReactNode;
  /** Whether the section starts expanded. Defaults to true. */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * A collapsible titled card. Uncontrolled -- each instance owns its own
 * open/closed state, so a page rendering many sections (the Investment
 * Memo) does not need to lift state for every one of them.
 */
export function CollapsibleSection({
  title,
  headerExtra,
  children,
  defaultOpen = true,
  className,
}: CollapsibleSectionProps): JSX.Element {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <div className={cn("rounded-card border border-line bg-surface shadow-card", className)}>
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        aria-expanded={isOpen}
        aria-controls={contentId}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-card px-6 py-4 text-left",
          "transition-colors duration-150 hover:bg-canvas",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
          "focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        )}
      >
        <span className="flex items-center gap-3">
          <span className="text-sm font-semibold text-ink">{title}</span>
          {headerExtra}
        </span>
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          className={cn(
            "h-4 w-4 shrink-0 text-muted transition-transform duration-150",
            isOpen ? "rotate-180" : "rotate-0",
          )}
        >
          <path
            d="M5 7.5 10 12.5 15 7.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <div id={contentId} hidden={!isOpen} className="border-t border-line px-6 py-4">
        {children}
      </div>
    </div>
  );
}
