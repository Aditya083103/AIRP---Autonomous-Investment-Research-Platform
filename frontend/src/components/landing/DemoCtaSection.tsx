// frontend/src/components/landing/DemoCtaSection.tsx
// Landing page (T-055) — the "live demo CTA" acceptance criterion. A
// dedicated, high-contrast band separate from the hero's CTA so the CTA
// still reads as an obvious next step for someone who scrolled past the
// hero to read the committee and how-it-works sections first.
//
// B10: the whole band fades/rises in via Reveal on mount.
//
// ISSUE 5: this band used to be `bg-ink` -- an intentional "inverted
// dark accent" that stood out against the rest of a LIGHT page. Now that
// the whole page is dark (see tailwind.config.ts's own ISSUE 5 note),
// `bg-ink` would instead render as a near-WHITE band (ink is now the
// light foreground colour) with white-on-white text -- the opposite of
// "stands out". A violet-tinted gradient over the standard dark surface,
// with a glowing accent border, is this theme's equivalent way to make
// one band read as "the important one": still visually distinct from
// the plain surface cards around it, still high-contrast, just achieved
// with an accent glow instead of an inverted fill.

import { Link } from "react-router-dom";

import { Reveal } from "@/components/motion/Reveal";

/** Full-width call-to-action band inviting the reader to start a real analysis. */
export function DemoCtaSection(): JSX.Element {
  return (
    <section className="py-16">
      <Reveal>
        <div className="rounded-card border border-brand-500/30 bg-gradient-to-br from-brand-900/50 via-surface to-surface px-8 py-12 text-center shadow-card sm:px-16">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-300">
            Try it yourself
          </p>
          <h2 className="mx-auto mt-3 max-w-xl font-display text-3xl font-semibold text-ink">
            Pick an Indian equity. Watch the committee work.
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-muted">
            Every analysis is free to run on the demo stack, streams live over WebSocket, and ends
            with a memo you can download.
          </p>
          <Link
            to="/analysis"
            className="mt-8 inline-flex h-12 items-center justify-center rounded-card bg-brand-500 px-6 text-base font-medium text-white transition-colors hover:bg-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
          >
            Start a free analysis
          </Link>
        </div>
      </Reveal>
    </section>
  );
}
