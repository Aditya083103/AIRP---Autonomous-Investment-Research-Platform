// frontend/src/components/graph/PipelineGraphNode.tsx
// AIRP -- custom ReactFlow node renderer for the pipeline graph (T-094)
//
// Every node in src/lib/graph/pipelineTopology.ts uses type: "pipelineNode",
// mapped to this component via PipelineGraphView's `nodeTypes`. Renders a
// design-system-styled card (Card's own rounded-card/shadow-card tokens,
// not a bespoke shape) coloured by PipelineNodeData.kind, matching the
// colour legend already established in docs/AIRP_Architecture.drawio
// (research agents blue, decision agents red, portfolio manager green).
// The colour map and handle styling live in
// src/lib/graph/pipelineNodeStyles.ts (extracted T-096) so
// LiveGraphNode.tsx's live-status node renderer shares the exact same
// base look instead of a second, possibly-drifting copy.
//
// Each node exposes 4 named Handles -- target-top/source-bottom for the
// main top-to-bottom spine, and target-left/source-left for the two edges
// that intentionally run sideways instead (planner's ABORT short-circuit,
// and T-040's debate_loop -> contrarian_investor cycle). See
// pipelineTopology.ts's PIPELINE_EDGES for which handle id each edge uses.

import { Handle, Position, type NodeProps } from "reactflow";

import { cn } from "@/lib/cn";
import { PIPELINE_HANDLE_CLASS_NAME, PIPELINE_KIND_STYLES } from "@/lib/graph/pipelineNodeStyles";
import { type PipelineNodeData } from "@/lib/graph/pipelineTopology";

export function PipelineGraphNode({ data }: NodeProps<PipelineNodeData>): JSX.Element {
  const isBoundary = data.kind === "boundary";

  return (
    <div
      className={cn(
        "rounded-card border px-4 py-2.5 text-center shadow-card",
        isBoundary ? "w-24 rounded-full py-1.5 font-mono text-[11px]" : "w-52",
        PIPELINE_KIND_STYLES[data.kind],
      )}
      data-node-kind={data.kind}
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
