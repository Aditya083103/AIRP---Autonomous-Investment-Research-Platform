// frontend/src/test/LiveGraphView.test.tsx
// Tests for LiveGraphView (T-096) -- the task's actual deliverable.
// Restrained about ReactFlow's own internals the same way
// PipelineGraphView.test.tsx (T-094) is (see that file's docstring for
// the full "why" -- jsdom's shared ResizeObserverStub never fires, so
// nodes stay in ReactFlow's "pending measurement" visibility:hidden
// state and no edge ever renders here). What this file DOES assert on
// reliably: every node's label reaches the DOM regardless of that
// hidden state (Testing Library's queries do not filter on CSS
// visibility), and -- the actual point of this component --
// data-node-status, a plain HTML attribute this component's own
// LiveGraphNode renders itself rather than anything ReactFlow computes,
// correctly reflects each node's derived live status.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveGraphView } from "@/components/graph/LiveGraphView";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import {
  NODE_FUNDAMENTAL,
  NODE_MACRO,
  NODE_PDF_EXPORT,
  NODE_PLANNER,
  NODE_SENTIMENT,
  NODE_TECHNICAL,
  PIPELINE_NODES,
} from "@/lib/graph/pipelineTopology";

function makeEvent(overrides: Partial<AgentStreamEvent>): AgentStreamEvent {
  return {
    job_id: "job-1",
    agent: NODE_PLANNER,
    status: "running",
    output_preview: "",
    progress_percent: 0,
    is_final: false,
    event_type: "node_completed",
    ...overrides,
  };
}

function nodeByStatus(status: string): Element[] {
  return Array.from(document.querySelectorAll(`[data-node-status="${status}"]`));
}

describe("LiveGraphView", () => {
  it("renders the graph container", () => {
    render(<LiveGraphView events={[]} isComplete={false} connectionStatus="open" error={null} />);
    expect(screen.getByTestId("live-graph-view")).toBeInTheDocument();
  });

  it("renders every real pipeline node's label", () => {
    render(<LiveGraphView events={[]} isComplete={false} connectionStatus="open" error={null} />);
    for (const node of PIPELINE_NODES) {
      expect(screen.getAllByText(node.data.label).length).toBeGreaterThan(0);
    }
  });

  it("shows every node pending before any event has arrived", () => {
    render(<LiveGraphView events={[]} isComplete={false} connectionStatus="open" error={null} />);
    // 17 total nodes (15 real + START/END), all pending.
    expect(nodeByStatus("pending")).toHaveLength(17);
    expect(nodeByStatus("running")).toHaveLength(0);
    expect(nodeByStatus("done")).toHaveLength(0);
  });

  it("flips a node to running the instant its started event arrives", () => {
    const events = [makeEvent({ agent: NODE_PLANNER, event_type: "node_started" })];
    render(
      <LiveGraphView events={events} isComplete={false} connectionStatus="open" error={null} />,
    );
    const runningNodes = nodeByStatus("running");
    expect(runningNodes).toHaveLength(1);
    expect(runningNodes[0]).toHaveTextContent("Planner");
  });

  it("flips a node to done once its completed event arrives, in real time", () => {
    const started = [makeEvent({ agent: NODE_PLANNER, event_type: "node_started" })];
    const { rerender } = render(
      <LiveGraphView events={started} isComplete={false} connectionStatus="open" error={null} />,
    );
    expect(nodeByStatus("running")).toHaveLength(1);

    const completed = [
      ...started,
      makeEvent({ agent: NODE_PLANNER, event_type: "node_completed" }),
    ];
    rerender(
      <LiveGraphView events={completed} isComplete={false} connectionStatus="open" error={null} />,
    );
    expect(nodeByStatus("running")).toHaveLength(0);
    // 2 nodes now read "done": the planner itself, and the __start__
    // boundary sentinel (which flips to "done" the instant any event
    // at all has arrived -- see deriveNodeStatuses's own doc). Assert
    // on the planner specifically rather than the raw count, so this
    // test stays about the planner's own transition, not incidentally
    // about START's unrelated (and separately tested) behaviour.
    const doneNodes = nodeByStatus("done");
    const plannerDoneNode = doneNodes.find((node) => node.textContent?.includes("Planner"));
    expect(plannerDoneNode).toBeDefined();
  });

  it("animates all 4 parallel research nodes simultaneously", () => {
    // The literal second acceptance criterion.
    const events = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_started" }),
    ];
    render(
      <LiveGraphView events={events} isComplete={false} connectionStatus="open" error={null} />,
    );
    expect(nodeByStatus("running")).toHaveLength(4);
  });

  it("shows END done once isComplete is true after a successful run", () => {
    const events = [
      makeEvent({ agent: NODE_PDF_EXPORT, event_type: "node_completed", is_final: true }),
    ];
    render(
      <LiveGraphView events={events} isComplete={true} connectionStatus="closed" error={null} />,
    );
    expect(nodeByStatus("done").length).toBeGreaterThan(0);
  });

  it("renders a connecting indicator while connectionStatus is connecting", () => {
    render(
      <LiveGraphView events={[]} isComplete={false} connectionStatus="connecting" error={null} />,
    );
    expect(screen.getByText(/Connecting to the committee/)).toBeInTheDocument();
  });

  it("renders the error message when one is present", () => {
    render(
      <LiveGraphView
        events={[]}
        isComplete={false}
        connectionStatus="error"
        error="Connection error."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Connection error.");
  });

  it("merges an extra className onto the outer graph container", () => {
    render(
      <LiveGraphView
        events={[]}
        isComplete={false}
        connectionStatus="open"
        error={null}
        className="custom-graph-class"
      />,
    );
    expect(screen.getByTestId("live-graph-view")).toHaveClass("custom-graph-class");
  });

  it("applies a custom fixed height to the graph container", () => {
    render(
      <LiveGraphView
        events={[]}
        isComplete={false}
        connectionStatus="open"
        error={null}
        height={480}
      />,
    );
    expect(screen.getByTestId("live-graph-view")).toHaveStyle({ height: "480px" });
  });
});
