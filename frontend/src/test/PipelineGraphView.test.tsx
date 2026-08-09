// frontend/src/test/PipelineGraphView.test.tsx
// Tests for PipelineGraphView (T-094). Deliberately restrained, matching
// StockPriceChart.test.tsx's own documented precedent for not asserting on
// a third-party visualisation library's internals (there, Recharts; here,
// ReactFlow) -- only the container, and that every real pipeline node's
// label actually made it into the rendered DOM.
//
// Edge rendering (paths, markers, and edge labels -- including the
// debate_loop cycle's "DEBATE_AGAIN" label) is deliberately NOT asserted
// on here. ReactFlow only computes edge geometry once it has measured
// every node's real DOM dimensions via ResizeObserver; jsdom's shared
// ResizeObserverStub (src/test/setup.ts, used by every chart test in this
// suite) never fires a callback, so nodes never leave ReactFlow's
// "pending measurement" state and no edge -- including its label -- ever
// renders in this environment. The debate_loop cycle's structural
// correctness (source/target) and its distinguishing `animated: true`
// styling are already covered, reliably, at the data layer in
// pipelineTopology.test.ts -- the right layer for that assertion, per
// this same "don't fight the library's internals" restraint.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineGraphView } from "@/components/graph/PipelineGraphView";
import { PIPELINE_NODES } from "@/lib/graph/pipelineTopology";

describe("PipelineGraphView", () => {
  it("renders the graph container", () => {
    render(<PipelineGraphView />);
    expect(screen.getByTestId("pipeline-graph-view")).toBeInTheDocument();
  });

  it("renders every real pipeline node's label, including START and END", () => {
    render(<PipelineGraphView />);
    for (const node of PIPELINE_NODES) {
      // getAllByText -- ReactFlow renders each node in both its normal pane
      // and (once zoomed/panned) a duplicate accessibility layer in some
      // versions, so asserting "at least one" is the robust check here.
      expect(screen.getAllByText(node.data.label).length).toBeGreaterThan(0);
    }
  });

  it("merges an extra className onto the outer container", () => {
    render(<PipelineGraphView className="custom-graph-class" />);
    expect(screen.getByTestId("pipeline-graph-view")).toHaveClass("custom-graph-class");
  });

  it("applies a custom fixed height to the outer container", () => {
    render(<PipelineGraphView height={480} />);
    expect(screen.getByTestId("pipeline-graph-view")).toHaveStyle({ height: "480px" });
  });
});
