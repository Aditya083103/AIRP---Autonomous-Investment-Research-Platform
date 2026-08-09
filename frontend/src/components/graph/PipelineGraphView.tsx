// frontend/src/components/graph/PipelineGraphView.tsx
// AIRP -- static pipeline topology graph (T-094)
//
// Renders the fixed node/edge topology from src/lib/graph/pipelineTopology.ts
// via ReactFlow. This is deliberately STATIC for T-094 -- every node always
// renders in its default (undifferentiated) visual state. T-095/T-096 add
// the live WebSocket-driven pending/running/done state machine on top of
// this same topology; this component's job is only to prove the topology
// itself renders correctly and matches backend/graph/graph.py's actual
// add_edge()/add_conditional_edges() calls (T-094's acceptance criteria).
//
// nodes/edges are passed straight from the static PIPELINE_NODES/
// PIPELINE_EDGES arrays (module-level constants, stable references across
// renders) rather than through useState/useMemo -- there is no local
// mutation of graph state in this component, so ReactFlow's own internal
// state (pan/zoom position) is the only thing that changes after mount.
//
// panOnDrag/zoomOnScroll stay enabled (unlike nodesDraggable/
// nodesConnectable, which are disabled) so a reader can still explore a
// graph this tall by panning and zooming -- only editing the topology
// itself is disabled, which would make no sense for a graph whose shape is
// defined entirely in code.

import { Background, BackgroundVariant, Controls, ReactFlow, type NodeTypes } from "reactflow";
import "reactflow/dist/style.css";

import { PipelineGraphNode } from "@/components/graph/PipelineGraphNode";
import { cn } from "@/lib/cn";
import { PIPELINE_EDGES, PIPELINE_NODES } from "@/lib/graph/pipelineTopology";

const NODE_TYPES: NodeTypes = { pipelineNode: PipelineGraphNode };

export interface PipelineGraphViewProps {
  /** Extra classes for the outer container (e.g. width constraints from a parent grid). */
  className?: string;
  /** Fixed pixel height for the ReactFlow viewport -- requires an explicit, non-zero size. */
  height?: number;
}

/** Renders the full 15-node AIRP LangGraph pipeline as a static, pannable/zoomable graph. */
export function PipelineGraphView({
  className,
  height = 640,
}: PipelineGraphViewProps): JSX.Element {
  return (
    <div
      className={cn("overflow-hidden rounded-card border border-line bg-canvas", className)}
      style={{ height }}
      data-testid="pipeline-graph-view"
    >
      <ReactFlow
        nodes={PIPELINE_NODES}
        edges={PIPELINE_EDGES}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
