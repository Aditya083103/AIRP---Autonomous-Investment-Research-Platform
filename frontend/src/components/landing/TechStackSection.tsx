// frontend/src/components/landing/TechStackSection.tsx
// Landing page (T-055) — the "tech stack logos" acceptance criterion.
// Rendered as plain-text wordmark chips rather than fetched brand-logo
// artwork: no third-party logo assets ship with this component, and a
// monospace chip row reads as "receipts" (the actual tools used) rather
// than a decorative logo wall.

const STACK: readonly string[] = [
  "React 18",
  "TypeScript",
  "Tailwind CSS",
  "FastAPI",
  "LangGraph",
  "LangChain",
  "PostgreSQL",
  "ChromaDB",
  "Redis",
  "Groq Llama 3.3",
];

/** A row of technology wordmark chips: what the system is actually built with. */
export function TechStackSection(): JSX.Element {
  return (
    <section className="py-16">
      <p className="text-center font-mono text-xs uppercase tracking-[0.2em] text-muted">
        Built with
      </p>
      <ul className="mt-6 flex flex-wrap items-center justify-center gap-3">
        {STACK.map((tech) => (
          <li
            key={tech}
            className="rounded-full border border-line bg-surface px-4 py-1.5 font-mono text-xs font-medium text-ink"
          >
            {tech}
          </li>
        ))}
      </ul>
    </section>
  );
}
