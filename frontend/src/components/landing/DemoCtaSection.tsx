// frontend/src/components/landing/DemoCtaSection.tsx
// Landing page (T-055) — the "live demo CTA" acceptance criterion. A
// dedicated, high-contrast band separate from the hero's CTA so the CTA
// still reads as an obvious next step for someone who scrolled past the
// hero to read the committee and how-it-works sections first.
//
// B10: the whole band fades/rises in via Reveal on mount.
//
// Broker-app redesign: back to a solid `bg-ink` band (near-black on this
// theme's near-white page) -- a flat, high-contrast block, not the
// previous dark-theme's translucent violet gradient-and-glow treatment.
// A gradient fill here was exactly the kind of decorative flourish that
// reads as "generated landing page" rather than a real product's own
// marketing page; a plain, bold-coloured block is how brokers themselves
// draw attention to one banner (see e.g. Kite's own signup CTA bands).

import { Link } from "react-router-dom";

import { Reveal } from "@/components/motion/Reveal";

/** Full-width call-to-action band inviting the reader to start a real analysis. */
export function DemoCtaSection(): JSX.Element {
  return (
    <section className="py-16">
      <Reveal>
        <div className="rounded-card bg-ink px-8 py-12 text-center shadow-card sm:px-16">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-300">
            Try it yourself
          </p>
          <h2 className="mx-auto mt-3 max-w-xl font-display text-3xl font-bold text-canvas">
            Pick an Indian equity. Watch the committee work.
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-canvas/70">
            Every analysis is free to run on the demo stack, streams live over WebSocket, and ends
            with a memo you can download.
          </p>
          <Link
            to="/analysis"
            className="mt-8 inline-flex h-12 items-center justify-center rounded-card bg-brand-500 px-6 text-base font-semibold text-white transition-colors hover:bg-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-ink"
          >
            Start a free analysis
          </Link>
        </div>
      </Reveal>
    </section>
  );
}
