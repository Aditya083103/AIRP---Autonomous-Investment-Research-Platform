// frontend/src/pages/ComponentsPreviewPage.tsx
// Component preview page (T-054). AIRP doesn't run Storybook -- one more
// build tool and dev-server port isn't worth it yet for eight primitives
// -- so this in-app route is the "Storybook or component preview page"
// half of the T-054 acceptance criteria: every design-system component,
// every variant, rendered together so a reviewer (or future-you) can see
// the whole system at a glance and visually regression-check it by eye.
// Routed at /dev/components; not linked from the product navigation.

import { useState, type ReactNode } from "react";

import { LiveGraphView, PipelineGraphView } from "@/components/graph";
import { Badge, Button, Card, Input, Modal, ProgressBar, Spinner, Tooltip } from "@/components/ui";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";

/** A labelled section wrapper so each component gets its own titled block. */
function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="border-b border-line py-10 first:pt-0 last:border-b-0">
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>
      <div className="mt-6 flex flex-wrap items-start gap-4">{children}</div>
    </section>
  );
}

/**
 * A scripted event stream for the LiveGraphView demo below (T-096) --
 * one batch of events per "step" a reviewer can advance through with
 * the Play/Reset controls, so the pending -> running -> done transition
 * and the 4 parallel research nodes lighting up together (T-096's two
 * acceptance criteria) are both visually checkable without a live
 * backend connection. Batch 2 in particular is the whole point: all 4
 * research nodes' started events land in the SAME step, exactly as the
 * real backend's Send-parallel fan-out (backend/graph/graph.py) does.
 */
function demoEvent(overrides: Partial<AgentStreamEvent>): AgentStreamEvent {
  return {
    job_id: "demo-job",
    agent: "planner",
    status: "running",
    output_preview: "",
    progress_percent: 0,
    is_final: false,
    event_type: "node_completed",
    ...overrides,
  };
}

const LIVE_GRAPH_DEMO_BATCHES: AgentStreamEvent[][] = [
  [demoEvent({ agent: "planner", event_type: "node_started" })],
  [demoEvent({ agent: "planner", event_type: "node_completed" })],
  [
    demoEvent({ agent: "fundamental_analyst", event_type: "node_started" }),
    demoEvent({ agent: "technical_analyst", event_type: "node_started" }),
    demoEvent({ agent: "sentiment_analyst", event_type: "node_started" }),
    demoEvent({ agent: "macro_economist", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "fundamental_analyst", event_type: "node_completed" }),
    demoEvent({ agent: "technical_analyst", event_type: "node_completed" }),
    demoEvent({ agent: "sentiment_analyst", event_type: "node_completed" }),
    demoEvent({ agent: "macro_economist", event_type: "node_completed" }),
  ],
  [demoEvent({ agent: "research_join", event_type: "node_started" })],
  [demoEvent({ agent: "research_join", event_type: "node_completed" })],
  [demoEvent({ agent: "contrarian_investor", event_type: "node_started" })],
  [
    demoEvent({ agent: "contrarian_investor", event_type: "node_completed" }),
    demoEvent({ agent: "debate_loop", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "debate_loop", event_type: "node_completed" }),
    demoEvent({ agent: "risk_officer", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "risk_officer", event_type: "node_completed" }),
    demoEvent({ agent: "valuation_agent", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "valuation_agent", event_type: "node_completed" }),
    demoEvent({ agent: "portfolio_manager", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "portfolio_manager", event_type: "node_completed" }),
    demoEvent({ agent: "report_generator", event_type: "node_started" }),
  ],
  [
    demoEvent({ agent: "report_generator", event_type: "node_completed" }),
    demoEvent({ agent: "pdf_export", event_type: "node_started" }),
  ],
  [demoEvent({ agent: "pdf_export", event_type: "node_completed", is_final: true })],
];

/** Interactive LiveGraphView demo (T-096) -- steps through LIVE_GRAPH_DEMO_BATCHES by hand. */
function LiveGraphDemo(): JSX.Element {
  const [step, setStep] = useState(0);
  const events = LIVE_GRAPH_DEMO_BATCHES.slice(0, step).flat();
  const isComplete = step >= LIVE_GRAPH_DEMO_BATCHES.length;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          onClick={() => setStep((current) => Math.max(0, current - 1))}
          disabled={step === 0}
        >
          Back
        </Button>
        <Button
          onClick={() =>
            setStep((current) => Math.min(LIVE_GRAPH_DEMO_BATCHES.length, current + 1))
          }
          disabled={isComplete}
        >
          Step forward
        </Button>
        <Button variant="secondary" onClick={() => setStep(0)}>
          Reset
        </Button>
        <span className="text-sm text-muted">
          Step {step} / {LIVE_GRAPH_DEMO_BATCHES.length}
        </span>
      </div>
      <div className="mt-6">
        <LiveGraphView
          events={events}
          isComplete={isComplete}
          connectionStatus={isComplete ? "closed" : "open"}
          error={null}
          className="w-full"
        />
      </div>
    </div>
  );
}

export function ComponentsPreviewPage(): JSX.Element {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [progress, setProgress] = useState(42);
  const [inputValue, setInputValue] = useState("");

  return (
    <div className="mx-auto max-w-4xl">
      <header>
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Design system</p>
        <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
          AIRP component preview
        </h1>
        <p className="mt-2 max-w-memo text-sm text-muted">
          Every T-054 primitive, every variant, in one place. Not part of the product navigation --
          visit directly at <code className="font-mono text-xs">/dev/components</code>.
        </p>
      </header>

      <Section title="Button">
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button isLoading>Loading</Button>
        <Button disabled>Disabled</Button>
        <Button size="sm">Small</Button>
        <Button size="lg">Large</Button>
      </Section>

      <Section title="Badge">
        <Badge>Neutral</Badge>
        <Badge tone="brand">Brand</Badge>
        <Badge tone="buy">BUY</Badge>
        <Badge tone="hold">HOLD</Badge>
        <Badge tone="sell">SELL</Badge>
      </Section>

      <Section title="Input">
        <Input
          label="Company name"
          placeholder="e.g. Infosys"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          hint="Search by name or ticker."
        />
        <Input label="With an error" defaultValue="TCSS" error="Ticker not found on NSE/BSE." />
        <Input label="Disabled" placeholder="Disabled field" disabled />
      </Section>

      <Section title="Card">
        <Card className="w-72">
          <Card.Header>
            <Card.Title>Fundamental Analyst</Card.Title>
            <Badge tone="buy">BUY</Badge>
          </Card.Header>
          <Card.Description>
            Revenue growth accelerating QoQ, margins stable, low leverage.
          </Card.Description>
          <Card.Footer>
            <Button size="sm" variant="secondary">
              View detail
            </Button>
          </Card.Footer>
        </Card>
      </Section>

      <Section title="Modal">
        <Button onClick={() => setIsModalOpen(true)}>Open modal</Button>
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title="Delete this analysis?"
          footer={
            <>
              <Button variant="ghost" onClick={() => setIsModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="danger" onClick={() => setIsModalOpen(false)}>
                Delete
              </Button>
            </>
          }
        >
          This permanently removes the saved analysis and its Investment Memo PDF. This cannot be
          undone.
        </Modal>
      </Section>

      <Section title="Spinner">
        <Spinner size="sm" />
        <Spinner size="md" />
        <Spinner size="lg" />
      </Section>

      <Section title="ProgressBar">
        <div className="w-full max-w-sm space-y-4">
          <ProgressBar label="Fundamental Analyst" value={progress} />
          <ProgressBar label="Technical Analyst" value={100} />
          <ProgressBar label="News Sentiment" value={0} />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setProgress((current) => Math.max(0, current - 10))}
            >
              -10
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setProgress((current) => Math.min(100, current + 10))}
            >
              +10
            </Button>
          </div>
        </div>
      </Section>

      <Section title="Tooltip">
        <Tooltip content="A 1-10 rating of how confident the Portfolio Manager is.">
          <Button variant="secondary">Hover or focus me</Button>
        </Tooltip>
        <Tooltip content="Appears below the trigger" placement="bottom">
          <Button variant="secondary">Bottom placement</Button>
        </Tooltip>
      </Section>

      <section className="border-b border-line py-10 first:pt-0 last:border-b-0">
        <h2 className="font-display text-xl font-semibold text-ink">Pipeline graph (T-094)</h2>
        <p className="mt-2 max-w-memo text-sm text-muted">
          The static LangGraph topology from{" "}
          <code className="font-mono text-xs">backend/graph/graph.py</code> -- all 15 real nodes
          plus the START/END sentinels, including the two mutually-exclusive T-032 routing branches
          and the T-040 debate_loop cycle (highlighted, animated). Every node here is rendered in
          its default state; T-096 wires this same topology to live WebSocket events.
        </p>
        <div className="mt-6">
          <PipelineGraphView className="w-full" />
        </div>
      </section>

      <section className="border-b border-line py-10 first:pt-0 last:border-b-0">
        <h2 className="font-display text-xl font-semibold text-ink">Live pipeline graph (T-096)</h2>
        <p className="mt-2 max-w-memo text-sm text-muted">
          {"The same topology, wired to a real (hand-scripted, for this preview) event " +
            'stream -- each node pulses "running" the instant its NODE_STARTED event ' +
            'arrives and flips to a checkmarked "done" on completion, exactly as it will ' +
            'during a live analysis run. Step forward to "Step 3" to see all 4 research ' +
            "nodes pulse simultaneously."}
        </p>
        <div className="mt-6">
          <LiveGraphDemo />
        </div>
      </section>
    </div>
  );
}
