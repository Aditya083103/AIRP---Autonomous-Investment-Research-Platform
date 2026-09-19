// frontend/src/components/landing/SectionDivider.tsx
// Landing page -- a deliberate seam between two consecutive sections.
// Before this, one section's `py-16` bottom padding butted straight
// into the next section's `py-16` top padding with nothing marking the
// boundary -- functionally fine, but the page read as one long
// undifferentiated scroll with no sense of "that topic ended, a new
// one is starting". A soft horizontal line that fades out at both ends
// (rather than a hard full-width rule, which would read as a table
// border) with a small centred accent dot reads as an intentional
// section break instead, using the brand violet already established
// as this page's one primary accent hue -- no new colour token needed.
//
// Deliberately carries no vertical padding of its own: it sits inside
// the ~64px of whitespace the adjacent sections' own `py-16` already
// produce (32px from the section above, 32px from the section below),
// so inserting it between two sections never changes the page's
// overall rhythm, only marks the midpoint of a gap that was already
// there.

import { cn } from "@/lib/cn";

export interface SectionDividerProps {
  className?: string;
}

/** A faded horizontal line with a centred accent dot, marking the boundary between two landing sections. */
export function SectionDivider({ className }: SectionDividerProps): JSX.Element {
  return (
    <div
      aria-hidden="true"
      role="presentation"
      data-testid="section-divider"
      className={cn("relative flex items-center justify-center", className)}
    >
      <div className="h-px w-full max-w-3xl bg-gradient-to-r from-transparent via-line to-transparent" />
      <span className="absolute h-1.5 w-1.5 rounded-full bg-brand-500/70" />
    </div>
  );
}
