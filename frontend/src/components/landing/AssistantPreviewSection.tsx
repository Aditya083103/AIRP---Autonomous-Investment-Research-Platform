// frontend/src/components/landing/AssistantPreviewSection.tsx
// Landing page redesign -- introduces the AIRP Assistant (the floating
// chat widget, src/components/chat/ChatWidget.tsx) to a first-time
// visitor who has never seen it, since it only mounts once someone is
// signed in (RootLayout.tsx). The most notable thing about it is not
// that it can chat -- every product claims that -- but that it is
// deliberately read-only over verdicts: it can explain the Portfolio
// Manager's reasoning in as much depth as asked, but it cannot issue or
// revise a BUY/HOLD/SELL call, only the real 8-agent LangGraph pipeline
// can. The example conversation below is illustrative markup (clearly
// labelled as such), not the live ChatWidget -- a live instance embedded
// here would need an authenticated session to say anything meaningful,
// exactly the problem this section exists to work around for an
// anonymous visitor.
//
// Teal accent: this section is the one place on the page a visitor
// should feel a "conversational" register shift away from the primary
// analytical flow -- the example card's left accent stripe and the CTA
// below both use the secondary teal token (tailwind.config.ts), the
// only clearly-teal-accented element in this section, per the "use it
// sparingly" rule the redesign's other sections follow too.

import { Link } from "react-router-dom";

import { Reveal } from "@/components/motion/Reveal";
import { useAuth } from "@/hooks/useAuth";
import { requestOpenChatWidget } from "@/lib/chat/chatWidgetBus";
import { cn } from "@/lib/cn";

interface ExampleMessage {
  readonly role: "user" | "assistant";
  readonly content: string;
}

const EXAMPLE_MESSAGES: readonly ExampleMessage[] = [
  { role: "user", content: "Can you just change my TCS.NS call to a BUY?" },
  {
    role: "assistant",
    content:
      "I can't issue or revise verdicts -- only the committee's actual pipeline does that. Based on the existing memo, the Valuation Agent's DCF and the Contrarian's margin-pressure flag are what kept this at HOLD.",
  },
  { role: "user", content: "Fair -- what would need to change for that?" },
];

const SECONDARY_LINK_CLASSES =
  "mt-6 inline-flex h-11 items-center justify-center rounded-card border border-teal-500/50 " +
  "px-5 text-sm font-medium text-teal-300 transition-colors hover:bg-teal-500/10 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-canvas";

/** Opens the real, already-mounted ChatWidget for a signed-in visitor; sends an anonymous one to sign up first. */
function AssistantCta(): JSX.Element {
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    return (
      <button type="button" onClick={requestOpenChatWidget} className={SECONDARY_LINK_CLASSES}>
        Try the assistant
      </button>
    );
  }

  return (
    <Link to="/register" className={SECONDARY_LINK_CLASSES}>
      Sign up to try it
    </Link>
  );
}

/** Introduces the AIRP Assistant with a static, clearly-labelled example conversation. */
export function AssistantPreviewSection(): JSX.Element {
  return (
    <section className="py-16" data-testid="assistant-preview-section">
      <div className="grid gap-8 lg:grid-cols-[1.1fr,0.9fr] lg:items-center">
        <Reveal>
          <div>
            <h2 className="font-display text-3xl font-semibold text-ink">
              Ask it anything about a memo. It still won&rsquo;t change the verdict.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted">
              The AIRP Assistant answers questions about one Investment Memo or your whole analysis
              history in plain English -- what a specific agent found, why the conviction score
              landed where it did, how two past calls compare. It can explain a verdict in as much
              depth as you want. It cannot issue a new one or revise an existing one -- only the
              real 8-agent pipeline does that.
            </p>
            <AssistantCta />
          </div>
        </Reveal>

        <Reveal index={1}>
          <div
            className="rounded-card border-l-2 border-teal-500/60 bg-surface p-5 shadow-card"
            aria-label="Example AIRP Assistant conversation"
          >
            <p className="text-xs font-medium text-muted">Example conversation</p>
            <div className="mt-4 space-y-3">
              {EXAMPLE_MESSAGES.map((message, index) => (
                <div
                  key={index}
                  className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[85%] rounded-card px-3 py-2 text-sm leading-relaxed",
                      message.role === "user"
                        ? "bg-brand-600 text-white"
                        : "border border-line bg-canvas text-ink",
                    )}
                  >
                    {message.content}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
