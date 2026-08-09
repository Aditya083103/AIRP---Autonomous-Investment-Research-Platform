// frontend/src/components/graph/LiveGraphNode.tsx
// AIRP -- custom ReactFlow node renderer for the LIVE pipeline graph (T-096)
//
// Sibling of T-094's PipelineGraphNode, not a modification of it --
// PipelineGraphNode is deliberately, permanently static (every node
// always renders in one undifferentiated visual state; see its own
// module docstring), so LiveGraphView (T-096) uses this component
// instead, registered as the "pipelineNode" type in its own ReactFlow
// instance. Both share the exact same base look (colour-by-kind, the 4
// named Handles, the boundary-node pill shape) via
// src/lib/graph/pipelineNodeStyles.ts -- this file's only job is the
// status-driven layer on top: an opacity dip for "pending", a pulsing
// ring for "running", and a small corner badge for "done"/"failed".
//
// Acceptance criteria this component is responsible for:
//   - "Nodes visibly pulse on start" -- the "running" ring uses
//     Tailwind's animate-pulse, respecting prefers-reduced-motion via
//     motion-reduce:animate-none (no new tailwind.config.ts keyframe
//     needed -- animate-pulse already ships with Tailwind).
//   - "flip to done on completion in real time" -- status is a prop,
//     recomputed by LiveGraphView on every new event
//     (src/lib/graph/liveGraphState.ts's deriveNodeStatuses), so a
//     completion event's re-render is the entire "in real time"
//     mechanism -- no timers or polling in this component at all.
//   - "parallel nodes animate simultaneously" -- each node's ring is
//     driven purely by ITS OWN `data.status` prop; four nodes that
//     happen to all be "running" at once render the identical
//     animate-pulse class independently, with no shared/coordinated
//     timer, so they read as synchronised for the same reason four
//     identical CSS animations starting in the same render frame do.

import { Handle, Position, type NodeProps } from "reactflow";

import { cn } from "@/lib/cn";
import { type LiveGraphNodeData, type PipelineNodeStatus } from "@/lib/graph/liveGraphState";
import { PIPELINE_HANDLE_CLASS_NAME, PIPELINE_KIND_STYLES } from "@/lib/graph/pipelineNodeStyles";

/** Ring/glow treatment layered on top of PIPELINE_KIND_STYLES's base colour, per live status. */
const STATUS_RING_CLASSES: Record<PipelineNodeStatus, string> = {
  pending: "",
  running: "ring-4 ring-brand-400 ring-offset-2 animate-pulse motion-reduce:animate-none",
  done: "ring-2 ring-emerald-500 ring-offset-1",
  failed: "ring-2 ring-verdict-sell ring-offset-1",
};

/** Small corner badge shown for "done"/"failed" -- omitted for "pending"/"running". */
const STATUS_BADGE: Record<PipelineNodeStatus, { symbol: string; className: string } | null> = {
  pending: null,
  running: null,
  done: { symbol: "\u2713", className: "bg-verdict-buy" },
  failed: { symbol: "!", className: "bg-verdict-sell" },
};

export function LiveGraphNode({ data }: NodeProps<LiveGraphNodeData>): JSX.Element {
  const isBoundary = data.kind === "boundary";
  const badge = STATUS_BADGE[data.status];

  return (
    <div
      className={cn(
        "relative rounded-card border px-4 py-2.5 text-center shadow-card",
        "transition-opacity duration-300",
        isBoundary ? "w-24 rounded-full py-1.5 font-mono text-[11px]" : "w-52",
        PIPELINE_KIND_STYLES[data.kind],
        STATUS_RING_CLASSES[data.status],
        data.status === "pending" && "opacity-50",
      )}
      data-node-kind={data.kind}
      data-node-status={data.status}
    >
      <Handle
        type="target"
        position={Position.Top}
        id="target-top"
        className={PIPELINE_HANDLE_CLASS_NAME}
      />
      <Handle
        type="target"
        position={Position.Left}
        id="target-left"
        className={PIPELINE_HANDLE_CLASS_NAME}
      />

      {badge ? (
        <span
          className={cn(
            "absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center",
            "rounded-full text-[11px] font-bold text-white shadow-card",
            badge.className,
          )}
          aria-label={data.status === "done" ? "Completed" : "Failed"}
        >
          {badge.symbol}
        </span>
      ) : null}
      {data.status === "running" ? (
        <span
          className={cn(
            "absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center gap-0.5",
            "rounded-full bg-brand-500 shadow-card",
          )}
          role="status"
          aria-label="Running"
        >
          {[0, 1, 2].map((dot) => (
            <span
              key={dot}
              className="h-1 w-1 animate-bounce rounded-full bg-white motion-reduce:animate-none"
              style={{ animationDelay: `${dot * 120}ms` }}
            />
          ))}
        </span>
      ) : null}

      <p className={cn("font-semibold leading-tight", isBoundary ? "" : "font-display text-sm")}>
        {data.label}
      </p>
      {data.subtitle ? (
        <p className="mt-1 text-[11px] leading-snug opacity-85">{data.subtitle}</p>
      ) : null}

      <Handle
        type="source"
        position={Position.Bottom}
        id="source-bottom"
        className={PIPELINE_HANDLE_CLASS_NAME}
      />
      <Handle
        type="source"
        position={Position.Left}
        id="source-left"
        className={PIPELINE_HANDLE_CLASS_NAME}
      />
    </div>
  );
}
