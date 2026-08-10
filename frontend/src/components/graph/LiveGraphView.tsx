// frontend/src/components/graph/LiveGraphView.tsx
// AIRP -- live, WebSocket-driven pipeline graph (T-096; T-097 adds the
// debate_loop cycle edge's own live animation below)
//
// T-094 proved the static topology renders correctly. T-095 gave the
// backend a NODE_STARTED event ahead of every completion event. This
// component is where those two land together: the same fixed
// PIPELINE_NODES/PIPELINE_EDGES topology (imported directly from
// src/lib/graph/pipelineTopology.ts -- this component never redefines
// the graph's shape, only its per-node/per-edge paint), rendered with
// LiveGraphNode (T-096's sibling of PipelineGraphNode) so every node
// shows its real, live pending/running/done/failed status derived by
// src/lib/graph/liveGraphState.ts's deriveNodeStatuses from the raw
// event stream.
//
// Props are deliberately shaped identically to
// src/components/progress/AgentProgressBoard.tsx's own props
// (events/isComplete/connectionStatus/error) -- both components are two
// different renderings of the exact same useAnalysisStream() output,
// and T-097's view toggle (src/pages/AnalysisResultPage.tsx) swaps
// between them with no adapter layer and no risk of losing stream
// state in between, since both read from the one useAnalysisStream()
// subscription that page already keeps running above the toggle
// regardless of which view is currently rendered. This component does
// not call useAnalysisStream itself, for the same reason
// AgentProgressBoard doesn't: a pure, props-driven component is
// trivially testable with hand-built event fixtures.
//
// nodes/edges recomputation (T-097 update)
// -------------------------------------------
// PIPELINE_NODES' per-node `data.status` and PIPELINE_EDGES' one live
// edge (the debate_loop cycle, DEBATE_LOOP_EDGE_ID) both change on
// every new event, so both arrays passed to ReactFlow are rebuilt
// together in a single useMemo keyed on [events, isComplete] -- one
// deriveNodeStatuses pass feeds both the per-node paint AND (via
// deriveDebateLoopEdgeState, which takes that same statuses object
// rather than re-deriving it) the cycle edge's animate/style overrides,
// so there is exactly one source of truth for "what is currently
// running" per render. Every OTHER edge is passed through completely
// unchanged from PIPELINE_EDGES -- T-097's acceptance criteria is
// entirely about the debate_loop cycle specifically, not a general
// live-edge system.

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
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
import {
  deriveDebateLoopEdgeState,
  deriveNodeStatuses,
  type LiveGraphNodeData,
} from "@/lib/graph/liveGraphState";
import {
  DEBATE_LOOP_EDGE_ID,
  PIPELINE_EDGES,
  PIPELINE_NODES,
  type PipelineNodeData,
} from "@/lib/graph/pipelineTopology";

const NODE_TYPES: NodeTypes = { pipelineNode: LiveGraphNode };

/** The DEBATE_AGAIN edge's stroke colour -- matches T-094's own static styling for this edge. */
const DEBATE_LOOP_COLOR = "#7C3AED";

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
  const { nodes, edges } = useMemo(() => {
    const statuses = deriveNodeStatuses(events, isComplete);
    const debateLoopState = deriveDebateLoopEdgeState(events, statuses);

    const liveNodes = PIPELINE_NODES.map((node: Node<PipelineNodeData>) => ({
      ...node,
      data: {
        ...node.data,
        status: statuses[node.id] ?? "pending",
      } satisfies LiveGraphNodeData,
    }));

    const liveEdges: Edge[] = PIPELINE_EDGES.map((edge: Edge) => {
      if (edge.id !== DEBATE_LOOP_EDGE_ID) {
        return edge;
      }

      // T-097: the DEBATE_AGAIN cycle edge is dimmed and static by
      // default (before the debate has started, in the brief gap
      // between round 1 finishing and round 2 starting, and once the
      // debate has concluded for good) and pulses -- ReactFlow's
      // marching-ants `animated`, full colour, thicker stroke -- while
      // `debateLoopState.active`. Because `active` flips true -> false
      // -> true -> false across a real 2-round debate (see
      // deriveDebateLoopEdgeState's own docstring), this single
      // boolean produces the "round-trip pulse... across its 2 rounds"
      // acceptance criterion with no separate round-1/round-2 styling
      // needed. The label additionally reports which round is current
      // while active, falling back to the neutral, round-less label
      // T-094 originally gave this edge otherwise.
      return {
        ...edge,
        animated: debateLoopState.active,
        label: debateLoopState.currentRound
          ? `DEBATE_AGAIN (round ${debateLoopState.currentRound} of 2)`
          : "DEBATE_AGAIN",
        style: debateLoopState.active
          ? { stroke: DEBATE_LOOP_COLOR, strokeWidth: 3 }
          : { stroke: DEBATE_LOOP_COLOR, strokeWidth: 2, opacity: 0.35 },
      };
    });

    return { nodes: liveNodes, edges: liveEdges };
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
          edges={edges}
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
