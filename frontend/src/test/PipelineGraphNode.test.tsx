// frontend/src/test/PipelineGraphNode.test.tsx
// Tests for PipelineGraphNode (T-094): renders label + optional subtitle,
// and applies a distinct data-node-kind marker per PipelineNodeKind so the
// colour treatment can be sanity-checked without asserting on literal
// Tailwind class strings (which would make this test brittle to a future
// palette tweak).
//
// Every render is wrapped in <ReactFlowProvider> -- <Handle> (and other
// ReactFlow-internal components) read from a zustand store provided by
// ReactFlow's own context, which normally comes from the ancestor
// <ReactFlow> element. PipelineGraphView.test.tsx gets this for free by
// rendering the real <ReactFlow> wrapper; this file renders
// PipelineGraphNode standalone, so it must supply that context itself or
// every render throws ReactFlow's "not used zustand provider as an
// ancestor" error (reactflow.dev/error#001).

import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { describe, expect, it } from "vitest";

import { PipelineGraphNode } from "@/components/graph/PipelineGraphNode";
import { type PipelineNodeData } from "@/lib/graph/pipelineTopology";

// PipelineGraphNode only reads `data` off NodeProps, but NodeProps' other
// fields (id, selected, dragging, ...) are required by ReactFlow's own
// type, so every field is supplied explicitly here with inert values
// rather than reaching for a type-widening cast.
function renderNode(data: PipelineNodeData): void {
  render(
    <ReactFlowProvider>
      <PipelineGraphNode
        id="test-node"
        type="pipelineNode"
        data={data}
        selected={false}
        dragging={false}
        isConnectable
        zIndex={0}
        xPos={0}
        yPos={0}
      />
    </ReactFlowProvider>,
  );
}

describe("PipelineGraphNode", () => {
  it("renders the node label", () => {
    renderNode({ label: "Contrarian Investor", kind: "decision" });
    expect(screen.getByText("Contrarian Investor")).toBeInTheDocument();
  });

  it("renders the subtitle when provided", () => {
    renderNode({ label: "Planner", subtitle: "resolves ticker", kind: "planner" });
    expect(screen.getByText("resolves ticker")).toBeInTheDocument();
  });

  it("omits the subtitle paragraph when none is provided", () => {
    renderNode({ label: "START", kind: "boundary" });
    expect(screen.getByText("START")).toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  });

  it("marks its visual kind via data-node-kind for each PipelineNodeKind", () => {
    const kinds: PipelineNodeData["kind"][] = [
      "boundary",
      "planner",
      "research",
      "routing",
      "decision",
      "synthesis",
      "output",
    ];
    for (const kind of kinds) {
      const { unmount } = render(
        <ReactFlowProvider>
          <PipelineGraphNode
            id="test-node"
            type="pipelineNode"
            data={{ label: `${kind}-node`, kind }}
            selected={false}
            dragging={false}
            isConnectable
            zIndex={0}
            xPos={0}
            yPos={0}
          />
        </ReactFlowProvider>,
      );
      expect(screen.getByText(`${kind}-node`).closest(`[data-node-kind="${kind}"]`)).not.toBeNull();
      unmount();
    }
  });
});
