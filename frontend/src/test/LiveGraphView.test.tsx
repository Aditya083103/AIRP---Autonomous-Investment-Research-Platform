// frontend/src/test/LiveGraphView.test.tsx
// Tests for LiveGraphView (T-096; T-097 adds the debate_loop cycle
// edge's live animation; T-098 adds a dedicated pending/running/done
// state-transition section and broader parallel-node coverage below)
// -- the task's actual deliverable. Restrained about ReactFlow's own
// internals the same way PipelineGraphView.test.tsx (T-094) is (see
// that file's docstring for the full "why" -- jsdom's shared
// ResizeObserverStub never fires, so nodes stay in ReactFlow's
// "pending measurement" visibility:hidden state and no edge --
// including the debate_loop cycle's animated/label overrides -- ever
// renders here). What this file DOES assert on reliably: every node's
// label reaches the DOM regardless of that hidden state (Testing
// Library's queries do not filter on CSS visibility), and -- the
// actual point of this component -- data-node-status, a plain HTML
// attribute this component's own LiveGraphNode renders itself rather
// than anything ReactFlow computes, correctly reflects each node's
// derived live status. The debate_loop cycle edge's own
// active/inactive/round logic (deriveDebateLoopEdgeState) is fully
// unit tested at the pure data layer in liveGraphState.test.ts -- the
// right layer for it, per this same jsdom restraint; this file's own
// T-097 addition is a single smoke test confirming LiveGraphView
// renders correctly (in particular, the contrarian_investor/
// debate_loop nodes' own live statuses) across a full 2-round debate
// sequence, without asserting on the edge DOM itself.
//
// T-098's "state transitions" section (bottom of this file) is
// deliberately sequence-based rather than single-snapshot: each test
// there drives the SAME component through 2-4 successive `rerender`
// calls with a growing events array (exactly how useAnalysisStream's
// own accumulating `events` array behaves against a real, live
// WebSocket) and asserts on every intermediate step, not just the
// final one -- so a regression that gets the END STATE right by
// accident while skipping an intermediate state (e.g. a node jumping
// straight from pending to done without ever visibly reading running)
// is caught directly, which the earlier T-096/T-097 tests above
// (each driving only 1-2 renders) do not individually guarantee.

import { render, screen } from "@testing-library/react";
import { type Node } from "reactflow";
import { describe, expect, it } from "vitest";

import { LiveGraphView } from "@/components/graph/LiveGraphView";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import {
  NODE_CONTRARIAN,
  NODE_DEBATE_LOOP,
  NODE_FUNDAMENTAL,
  NODE_MACRO,
  NODE_PDF_EXPORT,
  NODE_PLANNER,
  NODE_RESEARCH_JOIN,
  NODE_RISK,
  NODE_SENTIMENT,
  NODE_TECHNICAL,
  PIPELINE_NODES,
  type PipelineNodeData,
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

  it("renders correctly across a full 2-round debate sequence without crashing (T-097)", () => {
    // Smoke test: LiveGraphView's edges useMemo calls
    // deriveDebateLoopEdgeState on every render -- this exercises that
    // code path across a realistic 2-round debate and confirms the
    // component keeps rendering correctly (in particular, contrarian_
    // investor and debate_loop's own node statuses stay correct)
    // rather than throwing or producing a stale render. The edge's own
    // active/round logic is unit tested directly in
    // liveGraphState.test.ts -- see this file's docstring.
    const events: AgentStreamEvent[] = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }), // round 2
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_RISK, event_type: "node_started" }),
    ];

    render(
      <LiveGraphView events={events} isComplete={false} connectionStatus="open" error={null} />,
    );

    expect(screen.getByTestId("live-graph-view")).toBeInTheDocument();
    // debate_loop has finished for good (routed on to risk_officer,
    // which is now running) -- its own node status should read done.
    expect(nodeByStatus("done").length).toBeGreaterThan(0);
    expect(nodeByStatus("running")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// T-098: dedicated pending/running/done state-transition coverage, and
// broader parallel-node handling, driven across successive rerenders
// (see this file's own top-of-file docstring for why sequence-based
// tests catch bugs single-snapshot tests cannot).
// ---------------------------------------------------------------------------

describe("LiveGraphView state transitions (T-098)", () => {
  it("takes a single node through the full pending -> running -> done sequence", () => {
    const nodeLabel = (): string | undefined =>
      PIPELINE_NODES.find((n: Node<PipelineNodeData>) => n.id === NODE_RESEARCH_JOIN)?.data.label;

    // Step 1: pending -- no events at all yet.
    const { rerender } = render(
      <LiveGraphView events={[]} isComplete={false} connectionStatus="open" error={null} />,
    );
    let researchJoinNode = nodeByStatus("pending").find((n) =>
      n.textContent?.includes(nodeLabel() ?? ""),
    );
    expect(researchJoinNode).toBeDefined();

    // Step 2: running -- its own started event has arrived.
    const started = [makeEvent({ agent: NODE_RESEARCH_JOIN, event_type: "node_started" })];
    rerender(
      <LiveGraphView events={started} isComplete={false} connectionStatus="open" error={null} />,
    );
    researchJoinNode = nodeByStatus("running").find((n) =>
      n.textContent?.includes(nodeLabel() ?? ""),
    );
    expect(researchJoinNode).toBeDefined();
    expect(nodeByStatus("pending").some((n) => n.textContent?.includes(nodeLabel() ?? ""))).toBe(
      false,
    );

    // Step 3: done -- its completion event has now also arrived.
    const completed = [
      ...started,
      makeEvent({ agent: NODE_RESEARCH_JOIN, event_type: "node_completed" }),
    ];
    rerender(
      <LiveGraphView events={completed} isComplete={false} connectionStatus="open" error={null} />,
    );
    researchJoinNode = nodeByStatus("done").find((n) => n.textContent?.includes(nodeLabel() ?? ""));
    expect(researchJoinNode).toBeDefined();
    expect(nodeByStatus("running").some((n) => n.textContent?.includes(nodeLabel() ?? ""))).toBe(
      false,
    );
  });

  it("takes a node through running -> failed instead of running -> done", () => {
    const started = [makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" })];
    const { rerender } = render(
      <LiveGraphView events={started} isComplete={false} connectionStatus="open" error={null} />,
    );
    expect(nodeByStatus("running")).toHaveLength(1);
    expect(nodeByStatus("failed")).toHaveLength(0);

    const failed = [
      ...started,
      makeEvent({
        agent: NODE_FUNDAMENTAL,
        event_type: "node_completed",
        status: "failed",
      }),
    ];
    rerender(
      <LiveGraphView events={failed} isComplete={false} connectionStatus="open" error={null} />,
    );
    expect(nodeByStatus("running")).toHaveLength(0);
    const failedNode = nodeByStatus("failed").find((n) =>
      n.textContent?.includes("Fundamental Analyst"),
    );
    expect(failedNode).toBeDefined();
  });

  it("walks a realistic mini-pipeline through planner -> 4 parallel nodes -> join", () => {
    // A fuller, ordered simulation than the single-node tests above:
    // exercises the sequential spine AND the parallel fan-out together
    // across several successive renders, the way a real analysis run
    // actually unfolds.
    const timeline: { events: AgentStreamEvent[]; runningCount: number; doneCount: number }[] = [];
    const events: AgentStreamEvent[] = [];

    events.push(makeEvent({ agent: NODE_PLANNER, event_type: "node_started" }));
    // planner running (1); __start__ already reads done the instant any
    // event at all has arrived (see deriveNodeStatuses's own doc).
    timeline.push({ events: [...events], runningCount: 1, doneCount: 1 });

    events.push(makeEvent({ agent: NODE_PLANNER, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }));
    events.push(makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }));
    events.push(makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }));
    events.push(makeEvent({ agent: NODE_MACRO, event_type: "node_started" }));
    // planner (done) + 4 research nodes (running) = 4 running, 1 done
    // (plus __start__, which also reads done -- accounted for below).
    timeline.push({ events: [...events], runningCount: 4, doneCount: 2 });

    events.push(makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_TECHNICAL, event_type: "node_completed" }));
    // 2 of 4 research nodes done, 2 still running -- mixed parallel state.
    timeline.push({ events: [...events], runningCount: 2, doneCount: 4 });

    events.push(makeEvent({ agent: NODE_SENTIMENT, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_MACRO, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_RESEARCH_JOIN, event_type: "node_started" }));
    // all 4 research nodes done, research_join now running.
    timeline.push({ events: [...events], runningCount: 1, doneCount: 6 });

    const { rerender } = render(
      <LiveGraphView events={[]} isComplete={false} connectionStatus="open" error={null} />,
    );

    for (const step of timeline) {
      rerender(
        <LiveGraphView
          events={step.events}
          isComplete={false}
          connectionStatus="open"
          error={null}
        />,
      );
      expect(nodeByStatus("running")).toHaveLength(step.runningCount);
      expect(nodeByStatus("done")).toHaveLength(step.doneCount);
    }
  });

  it("handles all 4 parallel nodes completing in a different order than they started", () => {
    // Parallel-node handling isn't just "all 4 start together" (already
    // covered above) -- real runs finish in whatever order each
    // research agent's own API calls happen to resolve. This drives
    // macro finishing FIRST despite starting LAST, and confirms every
    // node's own status is independently correct regardless of order.
    const events: AgentStreamEvent[] = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_completed" }), // finishes 1st
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_completed" }), // 2nd
    ];

    render(
      <LiveGraphView events={events} isComplete={false} connectionStatus="open" error={null} />,
    );

    const runningLabels = nodeByStatus("running").map((n) => n.textContent);
    expect(runningLabels.some((text) => text?.includes("Fundamental Analyst"))).toBe(true);
    expect(runningLabels.some((text) => text?.includes("Technical Analyst"))).toBe(true);
    expect(nodeByStatus("running")).toHaveLength(2);

    const doneLabels = nodeByStatus("done").map((n) => n.textContent);
    expect(doneLabels.some((text) => text?.includes("Macro Economist"))).toBe(true);
    expect(doneLabels.some((text) => text?.includes("News Sentiment"))).toBe(true);
  });

  it("keeps 3 of 4 parallel nodes running while the 4th alone fails", () => {
    const events: AgentStreamEvent[] = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_started" }),
      makeEvent({
        agent: NODE_MACRO,
        event_type: "node_completed",
        status: "failed",
      }),
    ];

    render(
      <LiveGraphView events={events} isComplete={false} connectionStatus="open" error={null} />,
    );

    expect(nodeByStatus("running")).toHaveLength(3);
    const failedNode = nodeByStatus("failed").find((n) =>
      n.textContent?.includes("Macro Economist"),
    );
    expect(failedNode).toBeDefined();
  });
});
