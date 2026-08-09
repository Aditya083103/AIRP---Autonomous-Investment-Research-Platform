// frontend/src/components/graph/PipelineGraphNode.tsx
// AIRP -- custom ReactFlow node renderer for the pipeline graph (T-094)
//
// Every node in src/lib/graph/pipelineTopology.ts uses type: "pipelineNode",
// mapped to this component via PipelineGraphView's `nodeTypes`. Renders a
// design-system-styled card (Card's own rounded-card/shadow-card tokens,
// not a bespoke shape) coloured by PipelineNodeData.kind, matching the
// colour legend already established in docs/AIRP_Architecture.drawio
// (research agents blue, decision agents red, portfolio manager green).
//
// Each node exposes 4 named Handles -- target-top/source-bottom for the
// main top-to-bottom spine, and target-left/source-left for the two edges
// that intentionally run sideways instead (planner's ABORT short-circuit,
// and T-040's debate_loop -> contrarian_investor cycle). See
// pipelineTopology.ts's PIPELINE_EDGES for which handle id each edge uses.

import { Handle, Position, type NodeProps } from "reactflow";

import { cn } from "@/lib/cn";
import { type PipelineNodeData, type PipelineNodeKind } from "@/lib/graph/pipelineTopology";

const KIND_STYLES: Record<PipelineNodeKind, string> = {
  boundary: "border-line bg-canvas text-muted",
  planner: "border-brand-700 bg-brand-500 text-white",
  research: "border-blue-900 bg-blue-700 text-white",
  routing: "border-slate-700 bg-slate-500 text-white",
  decision: "border-red-800 bg-verdict-sell text-white",
  synthesis: "border-emerald-800 bg-verdict-buy text-white",
  output: "border-emerald-900 bg-emerald-800 text-white",
};

/** Shared handle styling -- small, low-contrast dots that don't compete visually with node text. */
const HANDLE_CLASS_NAME = "!h-2 !w-2 !border-none !bg-ink/30";

export function PipelineGraphNode({ data }: NodeProps<PipelineNodeData>): JSX.Element {
  const isBoundary = data.kind === "boundary";

  return (
    <div
      className={cn(
        "rounded-card border px-4 py-2.5 text-center shadow-card",
        isBoundary ? "w-24 rounded-full py-1.5 font-mono text-[11px]" : "w-52",
        KIND_STYLES[data.kind],
      )}
      data-node-kind={data.kind}
    >
      <Handle type="target" position={Position.Top} id="target-top" className={HANDLE_CLASS_NAME} />
      <Handle
        type="target"
        position={Position.Left}
        id="target-left"
        className={HANDLE_CLASS_NAME}
      />

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
        className={HANDLE_CLASS_NAME}
      />
      <Handle
        type="source"
        position={Position.Left}
        id="source-left"
        className={HANDLE_CLASS_NAME}
      />
    </div>
  );
}
