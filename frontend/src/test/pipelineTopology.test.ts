// frontend/src/test/pipelineTopology.test.ts
// Tests for src/lib/graph/pipelineTopology.ts (T-094). Pure data
// assertions only -- no rendering -- checking the static topology against
// backend/graph/graph.py's own documented node/edge list so a future
// change to graph.py's actual add_edge() calls has a clear, fast-failing
// counterpart here rather than only being caught by eye during review.

import { describe, expect, it } from "vitest";

import {
  DEBATE_LOOP_EDGE_ID,
  NODE_CONTRARIAN,
  NODE_DEBATE_LOOP,
  NODE_END,
  NODE_ERROR_HANDLER,
  NODE_FUNDAMENTAL,
  NODE_MACRO,
  NODE_PDF_EXPORT,
  NODE_PLANNER,
  NODE_PORTFOLIO_MANAGER,
  NODE_REPORT_GENERATOR,
  NODE_RESEARCH_JOIN,
  NODE_RISK,
  NODE_SENTIMENT,
  NODE_SENTIMENT_ESCALATION,
  NODE_START,
  NODE_TECHNICAL,
  NODE_VALUATION,
  PIPELINE_EDGES,
  PIPELINE_NODE_IDS,
  PIPELINE_NODES,
  RESEARCH_NODE_IDS,
  ROUTING_NODE_IDS,
} from "@/lib/graph/pipelineTopology";

describe("pipelineTopology", () => {
  it("defines exactly 15 real backend nodes plus the START/END sentinels (17 total)", () => {
    expect(PIPELINE_NODE_IDS).toHaveLength(15);
    expect(PIPELINE_NODES).toHaveLength(17);
  });

  it("has a unique node id for every node -- no accidental duplicates", () => {
    const ids = PIPELINE_NODES.map((node) => node.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("includes every node id backend/graph/graph.py registers via workflow.add_node", () => {
    const ids = new Set(PIPELINE_NODES.map((node) => node.id));
    const expectedIds = [
      NODE_START,
      NODE_PLANNER,
      NODE_FUNDAMENTAL,
      NODE_TECHNICAL,
      NODE_SENTIMENT,
      NODE_MACRO,
      NODE_RESEARCH_JOIN,
      NODE_ERROR_HANDLER,
      NODE_SENTIMENT_ESCALATION,
      NODE_CONTRARIAN,
      NODE_DEBATE_LOOP,
      NODE_RISK,
      NODE_VALUATION,
      NODE_PORTFOLIO_MANAGER,
      NODE_REPORT_GENERATOR,
      NODE_PDF_EXPORT,
      NODE_END,
    ];
    for (const id of expectedIds) {
      expect(ids.has(id)).toBe(true);
    }
  });

  it("lists exactly the 4 research agents that run in parallel", () => {
    expect(RESEARCH_NODE_IDS).toEqual([
      NODE_FUNDAMENTAL,
      NODE_TECHNICAL,
      NODE_SENTIMENT,
      NODE_MACRO,
    ]);
  });

  it("lists research_join plus the two T-032 routing branch nodes", () => {
    expect(ROUTING_NODE_IDS).toEqual([
      NODE_RESEARCH_JOIN,
      NODE_ERROR_HANDLER,
      NODE_SENTIMENT_ESCALATION,
    ]);
  });

  it("has a unique edge id for every edge -- no accidental duplicates", () => {
    const ids = PIPELINE_EDGES.map((edge) => edge.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every edge's source and target reference a real declared node id", () => {
    const nodeIds = new Set(PIPELINE_NODES.map((node) => node.id));
    for (const edge of PIPELINE_EDGES) {
      expect(nodeIds.has(edge.source)).toBe(true);
      expect(nodeIds.has(edge.target)).toBe(true);
    }
  });

  it("connects START to planner and pdf_export to END", () => {
    expect(PIPELINE_EDGES).toContainEqual(
      expect.objectContaining({ source: NODE_START, target: NODE_PLANNER }),
    );
    expect(PIPELINE_EDGES).toContainEqual(
      expect.objectContaining({ source: NODE_PDF_EXPORT, target: NODE_END }),
    );
  });

  it("fans planner out to all 4 research agents (the Send API parallel fan-out)", () => {
    for (const researchNodeId of RESEARCH_NODE_IDS) {
      expect(PIPELINE_EDGES).toContainEqual(
        expect.objectContaining({ source: NODE_PLANNER, target: researchNodeId }),
      );
    }
  });

  it("routes all 4 research agents into the single research_join barrier", () => {
    for (const researchNodeId of RESEARCH_NODE_IDS) {
      expect(PIPELINE_EDGES).toContainEqual(
        expect.objectContaining({ source: researchNodeId, target: NODE_RESEARCH_JOIN }),
      );
    }
  });

  it("branches research_join into its 3 conditional destinations (route_after_research)", () => {
    const destinations = [NODE_ERROR_HANDLER, NODE_SENTIMENT_ESCALATION, NODE_CONTRARIAN];
    for (const destination of destinations) {
      expect(PIPELINE_EDGES).toContainEqual(
        expect.objectContaining({ source: NODE_RESEARCH_JOIN, target: destination }),
      );
    }
  });

  it("routes both error_handler and sentiment_escalation forward to contrarian_investor", () => {
    expect(PIPELINE_EDGES).toContainEqual(
      expect.objectContaining({ source: NODE_ERROR_HANDLER, target: NODE_CONTRARIAN }),
    );
    expect(PIPELINE_EDGES).toContainEqual(
      expect.objectContaining({ source: NODE_SENTIMENT_ESCALATION, target: NODE_CONTRARIAN }),
    );
  });

  it("renders the debate_loop as a genuinely cyclical edge back to contrarian_investor", () => {
    const debateLoopEdge = PIPELINE_EDGES.find((edge) => edge.id === DEBATE_LOOP_EDGE_ID);
    expect(debateLoopEdge).toBeDefined();
    expect(debateLoopEdge?.source).toBe(NODE_DEBATE_LOOP);
    expect(debateLoopEdge?.target).toBe(NODE_CONTRARIAN);
    // The cyclic edge must be visually distinguishable from the rest of the
    // spine -- animated, and not sharing the plain default edge style.
    expect(debateLoopEdge?.animated).toBe(true);
  });

  it("proceeds from debate_loop to risk_officer (route_after_contrarian's PROCEED branch)", () => {
    expect(PIPELINE_EDGES).toContainEqual(
      expect.objectContaining({ source: NODE_DEBATE_LOOP, target: NODE_RISK }),
    );
  });

  it("wires the sequential tail: risk -> valuation -> portfolio_manager -> report -> pdf", () => {
    const tail: Array<[string, string]> = [
      [NODE_RISK, NODE_VALUATION],
      [NODE_VALUATION, NODE_PORTFOLIO_MANAGER],
      [NODE_PORTFOLIO_MANAGER, NODE_REPORT_GENERATOR],
      [NODE_REPORT_GENERATOR, NODE_PDF_EXPORT],
    ];
    for (const [source, target] of tail) {
      expect(PIPELINE_EDGES).toContainEqual(expect.objectContaining({ source, target }));
    }
  });

  it("gives every non-boundary node a non-empty label", () => {
    for (const node of PIPELINE_NODES) {
      expect(node.data.label.length).toBeGreaterThan(0);
    }
  });
});
