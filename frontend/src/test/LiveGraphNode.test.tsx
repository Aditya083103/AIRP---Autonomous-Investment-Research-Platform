// frontend/src/test/LiveGraphNode.test.tsx
// Tests for LiveGraphNode (T-096). Mirrors PipelineGraphNode.test.tsx's
// own <ReactFlowProvider> wrapping requirement (see that file's
// docstring for the full "why" -- <Handle>'s internal zustand-store
// hook needs an ancestor context this test provides directly, since it
// renders LiveGraphNode standalone rather than inside a real
// <ReactFlow>). Asserts on data-node-status (a stable test hook) rather
// than literal Tailwind ring/animation class strings, so a future
// palette or animation tweak does not make this test brittle.

import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { describe, expect, it } from "vitest";

import { LiveGraphNode } from "@/components/graph/LiveGraphNode";
import { type LiveGraphNodeData, type PipelineNodeStatus } from "@/lib/graph/liveGraphState";

function renderNode(data: LiveGraphNodeData): void {
  render(
    <ReactFlowProvider>
      <LiveGraphNode
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

describe("LiveGraphNode", () => {
  it("renders the node label", () => {
    renderNode({ label: "Fundamental Analyst", kind: "research", status: "pending" });
    expect(screen.getByText("Fundamental Analyst")).toBeInTheDocument();
  });

  it("renders the subtitle when provided", () => {
    renderNode({
      label: "Planner",
      subtitle: "resolves ticker",
      kind: "planner",
      status: "running",
    });
    expect(screen.getByText("resolves ticker")).toBeInTheDocument();
  });

  it("marks its live status via data-node-status for each PipelineNodeStatus", () => {
    const statuses: PipelineNodeStatus[] = ["pending", "running", "done", "failed"];
    for (const status of statuses) {
      const { unmount } = render(
        <ReactFlowProvider>
          <LiveGraphNode
            id="test-node"
            type="pipelineNode"
            data={{ label: `${status}-node`, kind: "decision", status }}
            selected={false}
            dragging={false}
            isConnectable
            zIndex={0}
            xPos={0}
            yPos={0}
          />
        </ReactFlowProvider>,
      );
      const node = screen.getByText(`${status}-node`);
      expect(node.closest(`[data-node-status="${status}"]`)).not.toBeNull();
      unmount();
    }
  });

  it("shows a 'Running' status badge only for the running state", () => {
    renderNode({ label: "Risk Officer", kind: "decision", status: "running" });
    expect(screen.getByRole("status", { name: "Running" })).toBeInTheDocument();
  });

  it("does not show a 'Running' badge for pending, done, or failed", () => {
    for (const status of ["pending", "done", "failed"] as const) {
      const { unmount } = render(
        <ReactFlowProvider>
          <LiveGraphNode
            id="test-node"
            type="pipelineNode"
            data={{ label: "Risk Officer", kind: "decision", status }}
            selected={false}
            dragging={false}
            isConnectable
            zIndex={0}
            xPos={0}
            yPos={0}
          />
        </ReactFlowProvider>,
      );
      expect(screen.queryByRole("status", { name: "Running" })).not.toBeInTheDocument();
      unmount();
    }
  });

  it("shows a 'Completed' badge for the done state", () => {
    renderNode({ label: "Valuation Agent", kind: "decision", status: "done" });
    expect(screen.getByLabelText("Completed")).toBeInTheDocument();
  });

  it("shows a 'Failed' badge for the failed state", () => {
    renderNode({ label: "Macro Economist", kind: "research", status: "failed" });
    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
  });

  it("shows no badge at all for the pending state", () => {
    renderNode({ label: "Report Generator", kind: "output", status: "pending" });
    expect(screen.queryByLabelText("Completed")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Running" })).not.toBeInTheDocument();
  });
});
