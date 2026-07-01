// frontend/src/pages/ComponentsPreviewPage.tsx
// Component preview page (T-054). AIRP doesn't run Storybook -- one more
// build tool and dev-server port isn't worth it yet for eight primitives
// -- so this in-app route is the "Storybook or component preview page"
// half of the T-054 acceptance criteria: every design-system component,
// every variant, rendered together so a reviewer (or future-you) can see
// the whole system at a glance and visually regression-check it by eye.
// Routed at /dev/components; not linked from the product navigation.

import { useState, type ReactNode } from "react";

import { Badge, Button, Card, Input, Modal, ProgressBar, Spinner, Tooltip } from "@/components/ui";

/** A labelled section wrapper so each component gets its own titled block. */
function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="border-b border-line py-10 first:pt-0 last:border-b-0">
      <h2 className="font-display text-xl font-semibold text-ink">{title}</h2>
      <div className="mt-6 flex flex-wrap items-start gap-4">{children}</div>
    </section>
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
    </div>
  );
}
