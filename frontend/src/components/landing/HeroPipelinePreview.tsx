// frontend/src/components/landing/HeroPipelinePreview.tsx
// Landing page redesign -- replaces the hero's old decorative gradient
// blob / floating 3D shape (formerly src/components/three/HeroScene.tsx,
// now deleted) with a small, purely client-side animation of AIRP's own
// pipeline: 4 research nodes activating together, then 3 debate-round
// nodes activating in sequence, then the Portfolio Manager completing,
// then a brief pause before the loop repeats. It is driven entirely by
// a local timer (STEPS below) -- there is no WebSocket connection and no
// backend call, unlike the real LiveGraphView this deliberately echoes
// the shape of (same PIPELINE_KIND_STYLES colour-by-kind treatment as
// PipelineGraphNode/LiveGraphNode, so a visitor who later runs a real
// analysis recognises this as the same system, not a generic decoration).
//
// prefers-reduced-motion: no timer is ever started and the component
// renders the single "everything just finished" frame -- the most
// informative static frame (every node reachable, nothing mid-flight)
// rather than freezing on an arbitrary in-progress moment.

import { useEffect, useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/cn";
import { PIPELINE_KIND_STYLES } from "@/lib/graph/pipelineNodeStyles";
import { type PipelineNodeKind } from "@/lib/graph/pipelineTopology";

type NodeStatus = "pending" | "running" | "done";

interface PreviewNode {
  readonly id: string;
  readonly label: string;
  readonly kind: PipelineNodeKind;
}

const RESEARCH_NODES: readonly PreviewNode[] = [
  { id: "fundamental", label: "Fundamental", kind: "research" },
  { id: "technical", label: "Technical", kind: "research" },
  { id: "sentiment", label: "Sentiment", kind: "research" },
  { id: "macro", label: "Macro", kind: "research" },
];

const DEBATE_NODES: readonly PreviewNode[] = [
  { id: "contrarian", label: "Contrarian", kind: "decision" },
  { id: "risk", label: "Risk Officer", kind: "decision" },
  { id: "valuation", label: "Valuation", kind: "decision" },
];

const PM_NODE: PreviewNode = { id: "pm", label: "Portfolio Manager", kind: "synthesis" };

interface FrameStatuses {
  readonly research: NodeStatus;
  readonly debate: readonly NodeStatus[];
  readonly pm: NodeStatus;
}

/** One frame per timeline step; `holdMs` is how long this frame stays on screen before the next one. */
interface Frame extends FrameStatuses {
  readonly holdMs: number;
}

const IDLE: FrameStatuses = {
  research: "pending",
  debate: ["pending", "pending", "pending"],
  pm: "pending",
};
const ALL_DONE: FrameStatuses = { research: "done", debate: ["done", "done", "done"], pm: "done" };

/** The scripted loop: 4 research nodes together, then 3 debate nodes one at a time, then the PM, then a pause. */
const TIMELINE: readonly Frame[] = [
  { ...IDLE, holdMs: 500 },
  { research: "running", debate: ["pending", "pending", "pending"], pm: "pending", holdMs: 1400 },
  { research: "done", debate: ["running", "pending", "pending"], pm: "pending", holdMs: 900 },
  { research: "done", debate: ["done", "running", "pending"], pm: "pending", holdMs: 900 },
  { research: "done", debate: ["done", "done", "running"], pm: "pending", holdMs: 900 },
  { research: "done", debate: ["done", "done", "done"], pm: "running", holdMs: 900 },
  { ...ALL_DONE, holdMs: 2200 },
];

const STATUS_RING_CLASSES: Record<NodeStatus, string> = {
  pending: "opacity-45",
  running: "ring-2 ring-brand-400 ring-offset-1 ring-offset-canvas animate-pulse",
  done: "ring-1 ring-emerald-500/70",
};

function PreviewNodeChip({ node, status }: { node: PreviewNode; status: NodeStatus }): JSX.Element {
  return (
    <div
      data-testid={`hero-pipeline-node-${node.id}`}
      data-node-status={status}
      className={cn(
        "rounded-card border px-2 py-1.5 text-center font-mono text-[10px] font-medium leading-tight",
        "break-words transition-all duration-300",
        PIPELINE_KIND_STYLES[node.kind],
        STATUS_RING_CLASSES[status],
      )}
    >
      {node.label}
    </div>
  );
}

function Connector(): JSX.Element {
  return (
    <div aria-hidden="true" className="flex justify-center py-1">
      <div className="h-3 w-px bg-line" />
    </div>
  );
}

export interface HeroPipelinePreviewProps {
  className?: string;
}

/** Illustrative, timer-driven animation of AIRP's research -> debate -> decision pipeline. */
export function HeroPipelinePreview({ className }: HeroPipelinePreviewProps): JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setFrameIndex((current) => (current + 1) % TIMELINE.length);
    }, TIMELINE[frameIndex]?.holdMs ?? 1000);
    return () => window.clearTimeout(timer);
  }, [frameIndex, prefersReducedMotion]);

  const statuses = prefersReducedMotion ? ALL_DONE : TIMELINE[frameIndex] ?? ALL_DONE;

  return (
    <div
      aria-hidden="true"
      data-testid="hero-pipeline-preview"
      className={cn("rounded-card bg-surface p-4 shadow-card", className)}
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {RESEARCH_NODES.map((node) => (
          <PreviewNodeChip key={node.id} node={node} status={statuses.research} />
        ))}
      </div>

      <Connector />

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {DEBATE_NODES.map((node, index) => (
          <PreviewNodeChip key={node.id} node={node} status={statuses.debate[index] ?? "pending"} />
        ))}
      </div>

      <Connector />

      <div className="mx-auto w-1/2 min-w-[7rem]">
        <PreviewNodeChip node={PM_NODE} status={statuses.pm} />
      </div>

      <p className="mt-3 text-center text-[11px] leading-relaxed text-muted">
        Illustrative preview of a live analysis run.
      </p>
    </div>
  );
}
