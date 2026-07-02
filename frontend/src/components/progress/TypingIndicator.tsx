// frontend/src/components/progress/TypingIndicator.tsx
// AIRP -- Animated typing indicator (T-059)
//
// Three dots bouncing with a staggered delay -- the classic "typing…"
// affordance, reused here for an agent card's "thinking" state. Pure
// CSS animation (Tailwind's built-in `animate-bounce` utility plus an
// inline `animationDelay` per dot for the stagger) -- no new
// tailwind.config.ts keyframes needed, and no JS timer driving it, so
// it costs nothing to keep running for as long as a card stays in the
// "thinking" state.

export function TypingIndicator(): JSX.Element {
  return (
    <span className="inline-flex items-center gap-1" role="status" aria-label="Thinking">
      {[0, 1, 2].map((dot) => (
        <span
          key={dot}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500"
          style={{ animationDelay: `${dot * 120}ms` }}
        />
      ))}
    </span>
  );
}
