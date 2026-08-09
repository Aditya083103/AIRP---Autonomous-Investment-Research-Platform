// frontend/src/components/graph/LiveGraphView.tsx
// AIRP -- live, WebSocket-driven pipeline graph (T-096)
//
// T-094 proved the static topology renders correctly. T-095 gave the
// backend a NODE_STARTED event ahead of every completion event. This
// component is where those two land together: the same fixed
// PIPELINE_NODES/PIPELINE_EDGES topology (unchanged, imported directly
// from src/lib/graph/pipelineTopology.ts -- this component never
// redefines the graph's shape, only its per-node paint), rendered with
// LiveGraphNode (T-096's sibling of PipelineGraphNode) so every node
// shows its real, live pending/running/done/failed status derived by
// src/lib/graph/liveGraphState.ts's deriveNodeStatuses from the raw
// event stream.
//
// Props are deliberately shaped identically to
// src/components/progress/AgentProgressBoard.tsx's own props
// (events/isComplete/progressPercent/connectionStatus/error) -- both
// components are two different renderings of the exact same
// useAnalysisStream() output, and T-097 ("view toggle") needs to be
// able to swap between them without an adapter layer or losing any
// stream state in between. This component does not call
// useAnalysisStream itself, for the same reason AgentProgressBoard
// doesn't: a pure, props-driven component is trivially testable with
// hand-built event fixtures, and the one real subscription lives at
// the page level (src/pages/AnalysisResultPage.tsx), not duplicated
// here.
//
// nodes/edges recomputation
// --------------------------
// PIPELINE_EDGES never changes (T-096 does not touch edge rendering --
// animating the debate_loop cycle specifically is T-097's job per the
// project plan). PIPELINE_NODES' per-node `data.status` DOES change on
// every new event, so the nodes array passed to ReactFlow is rebuilt
// via useMemo keyed on [events, isComplete] -- the same "new reference
// only when the derived output could actually differ" discipline
// PipelineGraphView (T-094) already established for its own (fully
// static) nodes/edges.

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Node,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";

import { LiveGraphNode } from "@/components/graph/LiveGraphNode";
import { Spinner } from "@/components/ui";
import {
  type AgentStreamEvent,
  type AnalysisStreamConnectionStatus,
} from "@/hooks/useAnalysisStream";
import { cn } from "@/lib/cn";
import { deriveNodeStatuses, type LiveGraphNodeData } from "@/lib/graph/liveGraphState";
import {
  PIPELINE_EDGES,
  PIPELINE_NODES,
  type PipelineNodeData,
} from "@/lib/graph/pipelineTopology";

const NODE_TYPES: NodeTypes = { pipelineNode: LiveGraphNode };

function describeConnection(
  connectionStatus: AnalysisStreamConnectionStatus,
  isComplete: boolean,
): string {
  if (connectionStatus === "connecting") {
    return "Connecting to the committee…";
  }
  if (connectionStatus === "open" && !isComplete) {
    return "Live — streaming agent updates";
  }
  if (connectionStatus === "closed" && isComplete) {
    return "Analysis complete";
  }
  if (connectionStatus === "error") {
    return "Connection error";
  }
  return connectionStatus;
}

export interface LiveGraphViewProps {
  events: readonly AgentStreamEvent[];
  isComplete: boolean;
  connectionStatus: AnalysisStreamConnectionStatus;
  error: string | null;
  /** Extra classes for the outer graph container (e.g. width constraints from a parent grid). */
  className?: string;
  /** Fixed pixel height for the ReactFlow viewport -- requires an explicit, non-zero size. */
  height?: number;
}

/** Renders the 15-node AIRP LangGraph pipeline with each node's real-time status. */
export function LiveGraphView({
  events,
  isComplete,
  connectionStatus,
  error,
  className,
  height = 640,
}: LiveGraphViewProps): JSX.Element {
  const nodes = useMemo(() => {
    const statuses = deriveNodeStatuses(events, isComplete);
    return PIPELINE_NODES.map((node: Node<PipelineNodeData>) => ({
      ...node,
      data: {
        ...node.data,
        status: statuses[node.id] ?? "pending",
      } satisfies LiveGraphNodeData,
    }));
  }, [events, isComplete]);

  return (
    <div>
      <div className="flex items-center gap-2 text-sm text-muted">
        {connectionStatus === "connecting" ? <Spinner size="sm" /> : null}
        <span>{describeConnection(connectionStatus, isComplete)}</span>
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-sm text-verdict-sell">
          {error}
        </p>
      ) : null}

      <div
        className={cn("mt-4 overflow-hidden rounded-card border border-line bg-canvas", className)}
        style={{ height }}
        data-testid="live-graph-view"
      >
        <ReactFlow
          nodes={nodes}
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
    </div>
  );
}
