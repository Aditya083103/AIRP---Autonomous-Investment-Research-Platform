// frontend/src/lib/graph/pipelineTopology.ts
// AIRP -- Static LangGraph pipeline topology (T-094)
//
// This is a hand-transcribed, 1:1 mirror of backend/graph/graph.py's
// build_graph() -- every workflow.add_edge(...) and
// workflow.add_conditional_edges(...) call in that file has exactly one
// corresponding entry in PIPELINE_EDGES below, and every workflow.add_node(...)
// call has exactly one corresponding entry in PIPELINE_NODES. START and END
// are also modelled explicitly (as a "boundary" kind) even though they are
// LangGraph's own langgraph.graph.START/END sentinels, not real nodes --
// backend/graph/graph_visualisation.py's own Mermaid export (T-034) renders
// them the same way, and dropping them here would silently disagree with
// that export.
//
// Node ids below are copied string-for-string from backend/graph/nodes.py's
// NODE_* constants (see the module-level re-export block at the bottom of
// this file) -- T-095/T-096 will match incoming WebSocket NODE_STARTED /
// node-completion event payloads against these exact same id strings, so
// nothing here is a free-form label choice.
//
// This file is pure data (no React, no side effects) so it can be unit
// tested against backend/graph/graph.py's own topology comment block
// without ever mounting a component -- see src/test/pipelineTopology.test.ts.
//
// Layout
// ------
// A single top-to-bottom column for the sequential spine, widening to a
// 4-across row for the parallel research fan-out and a 2-across row for the
// two mutually-exclusive T-032 routing branches (error_handler /
// sentiment_escalation -- only one of the three research_join outcomes is
// ever taken at runtime, but all three are rendered since this is the
// *static* topology, not a live run). Every coordinate is an arbitrary but
// fixed (x, y) pixel position -- ReactFlow's `fitView` prop scales/centers
// the whole graph to the container on mount, so the absolute numbers only
// need to preserve relative layout, not match any particular viewport size.
//
// The debate_loop cycle (T-040's route_after_contrarian DEBATE_AGAIN branch,
// debate_loop -> contrarian_investor) is the one edge in this file that
// points "backwards" up the column instead of down it -- see
// DEBATE_LOOP_EDGE_ID below for how it is styled to read as a loop rather
// than a stray reversed arrow.

import { MarkerType, type Edge, type Node } from "reactflow";

// ---------------------------------------------------------------------------
// Node ids -- string-for-string mirror of backend/graph/nodes.py's NODE_*
// constants, plus the two LangGraph sentinels START/END.
// ---------------------------------------------------------------------------

export const NODE_START = "__start__";
export const NODE_PLANNER = "planner";
export const NODE_FUNDAMENTAL = "fundamental_analyst";
export const NODE_TECHNICAL = "technical_analyst";
export const NODE_SENTIMENT = "sentiment_analyst";
export const NODE_MACRO = "macro_economist";
export const NODE_RESEARCH_JOIN = "research_join";
export const NODE_ERROR_HANDLER = "error_handler";
export const NODE_SENTIMENT_ESCALATION = "sentiment_escalation";
export const NODE_CONTRARIAN = "contrarian_investor";
export const NODE_DEBATE_LOOP = "debate_loop";
export const NODE_RISK = "risk_officer";
export const NODE_VALUATION = "valuation_agent";
export const NODE_PORTFOLIO_MANAGER = "portfolio_manager";
export const NODE_REPORT_GENERATOR = "report_generator";
export const NODE_PDF_EXPORT = "pdf_export";
export const NODE_END = "__end__";

/** The 4 research agents that run concurrently in the same LangGraph super-step. */
export const RESEARCH_NODE_IDS = [
  NODE_FUNDAMENTAL,
  NODE_TECHNICAL,
  NODE_SENTIMENT,
  NODE_MACRO,
] as const;

/** T-032's join + the two mutually-exclusive routing branches off research_join. */
export const ROUTING_NODE_IDS = [
  NODE_RESEARCH_JOIN,
  NODE_ERROR_HANDLER,
  NODE_SENTIMENT_ESCALATION,
] as const;

/** All 15 real backend/graph/nodes.py nodes -- excludes the __start__/__end__ sentinels. */
export const PIPELINE_NODE_IDS = [
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
] as const;

/** The id of the single "backwards" edge -- T-040's debate_loop -> contrarian_investor cycle. */
export const DEBATE_LOOP_EDGE_ID = "debate_loop-to-contrarian-DEBATE_AGAIN";

// ---------------------------------------------------------------------------
// Node data + visual kind
// ---------------------------------------------------------------------------

export type PipelineNodeKind =
  | "boundary" // __start__ / __end__
  | "planner" // planner
  | "research" // the 4 parallel research agents
  | "routing" // research_join, error_handler, sentiment_escalation
  | "decision" // contrarian_investor, debate_loop, risk_officer, valuation_agent
  | "synthesis" // portfolio_manager
  | "output"; // report_generator, pdf_export

export interface PipelineNodeData {
  /** Short node label, rendered in the node body. */
  label: string;
  /** Optional secondary line -- the node's mandate, in a few words. */
  subtitle?: string;
  /** Visual category driving PipelineGraphNode's colour treatment. */
  kind: PipelineNodeKind;
}

// ---------------------------------------------------------------------------
// Static node positions
// ---------------------------------------------------------------------------
// Column x-centres: single-column spine nodes centre at x=430 (width 220),
// the 4-across research row spans x=40..1040, the 2-across routing-branch
// row centres its two nodes either side of the spine.

export const PIPELINE_NODES: Node<PipelineNodeData>[] = [
  {
    id: NODE_START,
    type: "pipelineNode",
    position: { x: 480, y: 0 },
    data: { label: "START", kind: "boundary" },
  },
  {
    id: NODE_PLANNER,
    type: "pipelineNode",
    position: { x: 430, y: 100 },
    data: {
      label: "Planner",
      subtitle: "resolves ticker · inits InvestmentState",
      kind: "planner",
    },
  },
  {
    id: NODE_FUNDAMENTAL,
    type: "pipelineNode",
    position: { x: 40, y: 250 },
    data: { label: "Fundamental Analyst", subtitle: "yFinance · Alpha Vantage", kind: "research" },
  },
  {
    id: NODE_TECHNICAL,
    type: "pipelineNode",
    position: { x: 300, y: 250 },
    data: { label: "Technical Analyst", subtitle: "yFinance OHLCV", kind: "research" },
  },
  {
    id: NODE_SENTIMENT,
    type: "pipelineNode",
    position: { x: 560, y: 250 },
    data: { label: "News Sentiment", subtitle: "NewsAPI · ChromaDB RAG", kind: "research" },
  },
  {
    id: NODE_MACRO,
    type: "pipelineNode",
    position: { x: 820, y: 250 },
    data: { label: "Macro Economist", subtitle: "RBI scraper", kind: "research" },
  },
  {
    id: NODE_RESEARCH_JOIN,
    type: "pipelineNode",
    position: { x: 430, y: 400 },
    data: {
      label: "Research Join",
      subtitle: "sequential barrier -- all 4 must complete",
      kind: "routing",
    },
  },
  {
    id: NODE_ERROR_HANDLER,
    type: "pipelineNode",
    position: { x: 160, y: 540 },
    data: { label: "Error Handler", subtitle: "ROUTE_ERROR", kind: "routing" },
  },
  {
    id: NODE_SENTIMENT_ESCALATION,
    type: "pipelineNode",
    position: { x: 700, y: 540 },
    data: { label: "Sentiment Escalation", subtitle: "ROUTE_ESCALATE_SENTIMENT", kind: "routing" },
  },
  {
    id: NODE_CONTRARIAN,
    type: "pipelineNode",
    position: { x: 430, y: 680 },
    data: {
      label: "Contrarian Investor",
      subtitle: "deterministic + LLM bear case",
      kind: "decision",
    },
  },
  {
    id: NODE_DEBATE_LOOP,
    type: "pipelineNode",
    position: { x: 430, y: 820 },
    data: { label: "Debate Loop", subtitle: "records debate_rounds[]", kind: "decision" },
  },
  {
    id: NODE_RISK,
    type: "pipelineNode",
    position: { x: 430, y: 960 },
    data: {
      label: "Risk Officer",
      subtitle: "governance · fraud · regulatory",
      kind: "decision",
    },
  },
  {
    id: NODE_VALUATION,
    type: "pipelineNode",
    position: { x: 430, y: 1100 },
    data: {
      label: "Valuation Agent",
      subtitle: "DCF · PE/PB/EV-EBITDA vs peers",
      kind: "decision",
    },
  },
  {
    id: NODE_PORTFOLIO_MANAGER,
    type: "pipelineNode",
    position: { x: 430, y: 1240 },
    data: {
      label: "Portfolio Manager",
      subtitle: "BUY / HOLD / SELL + conviction",
      kind: "synthesis",
    },
  },
  {
    id: NODE_REPORT_GENERATOR,
    type: "pipelineNode",
    position: { x: 430, y: 1380 },
    data: { label: "Report Generator", subtitle: "structured Investment Memo", kind: "output" },
  },
  {
    id: NODE_PDF_EXPORT,
    type: "pipelineNode",
    position: { x: 430, y: 1520 },
    data: { label: "PDF Export", subtitle: "branded PDF via WeasyPrint", kind: "output" },
  },
  {
    id: NODE_END,
    type: "pipelineNode",
    position: { x: 480, y: 1660 },
    data: { label: "END", kind: "boundary" },
  },
];

// ---------------------------------------------------------------------------
// Static edges
// ---------------------------------------------------------------------------
// "handle" suffixes (-top/-bottom/-left) refer to the 4 named Handles every
// PipelineGraphNode renders (see PipelineGraphNode.tsx) -- the main spine
// flows top-handle -> bottom-handle downward; the two "sideways" edges
// (planner's ABORT short-circuit and the debate_loop cycle) instead use the
// left-side handles so they read visually as a branch/loop rather than a
// straight line overlapping the spine.

const ARROW = { type: MarkerType.ArrowClosed, width: 16, height: 16 } as const;

/** research_join's 3 conditional destinations (T-032's route_after_research) share this style. */
const CONDITIONAL_EDGE_STYLE = { stroke: "#94A3B8", strokeDasharray: "6 4" } as const;

export const PIPELINE_EDGES: Edge[] = [
  // -- START -> planner --------------------------------------------------
  {
    id: "start-to-planner",
    source: NODE_START,
    target: NODE_PLANNER,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },

  // -- planner -> Send fan-out (route_after_planner's 4 Send targets) ----
  {
    id: "planner-to-fundamental",
    source: NODE_PLANNER,
    target: NODE_FUNDAMENTAL,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "Send",
    markerEnd: ARROW,
  },
  {
    id: "planner-to-technical",
    source: NODE_PLANNER,
    target: NODE_TECHNICAL,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "Send",
    markerEnd: ARROW,
  },
  {
    id: "planner-to-sentiment",
    source: NODE_PLANNER,
    target: NODE_SENTIMENT,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "Send",
    markerEnd: ARROW,
  },
  {
    id: "planner-to-macro",
    source: NODE_PLANNER,
    target: NODE_MACRO,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "Send",
    markerEnd: ARROW,
  },

  // -- planner -> END (route_after_planner's ABORT short-circuit) --------
  {
    id: "planner-to-end-abort",
    source: NODE_PLANNER,
    target: NODE_END,
    sourceHandle: "source-left",
    targetHandle: "target-left",
    label: "ABORT",
    style: CONDITIONAL_EDGE_STYLE,
    markerEnd: ARROW,
  },

  // -- 4 research agents -> research_join (T-032 explicit join) ----------
  {
    id: "fundamental-to-join",
    source: NODE_FUNDAMENTAL,
    target: NODE_RESEARCH_JOIN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "technical-to-join",
    source: NODE_TECHNICAL,
    target: NODE_RESEARCH_JOIN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "sentiment-to-join",
    source: NODE_SENTIMENT,
    target: NODE_RESEARCH_JOIN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "macro-to-join",
    source: NODE_MACRO,
    target: NODE_RESEARCH_JOIN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },

  // -- research_join -> 3 conditional destinations (route_after_research) -
  {
    id: "join-to-error-handler",
    source: NODE_RESEARCH_JOIN,
    target: NODE_ERROR_HANDLER,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "ROUTE_ERROR",
    style: CONDITIONAL_EDGE_STYLE,
    markerEnd: ARROW,
  },
  {
    id: "join-to-sentiment-escalation",
    source: NODE_RESEARCH_JOIN,
    target: NODE_SENTIMENT_ESCALATION,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "ROUTE_ESCALATE_SENTIMENT",
    style: CONDITIONAL_EDGE_STYLE,
    markerEnd: ARROW,
  },
  {
    id: "join-to-contrarian",
    source: NODE_RESEARCH_JOIN,
    target: NODE_CONTRARIAN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "ROUTE_PROCEED",
    style: CONDITIONAL_EDGE_STYLE,
    markerEnd: ARROW,
  },

  // -- error_handler / sentiment_escalation -> contrarian (forward edges) -
  {
    id: "error-handler-to-contrarian",
    source: NODE_ERROR_HANDLER,
    target: NODE_CONTRARIAN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "sentiment-escalation-to-contrarian",
    source: NODE_SENTIMENT_ESCALATION,
    target: NODE_CONTRARIAN,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },

  // -- contrarian -> debate_loop (T-040: always runs after each round) ---
  {
    id: "contrarian-to-debate-loop",
    source: NODE_CONTRARIAN,
    target: NODE_DEBATE_LOOP,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },

  // -- debate_loop -> contrarian (T-040 cycle: route_after_contrarian's ---
  // DEBATE_AGAIN branch). This is the ONE edge that points back up the
  // spine -- routed via the left-side handles and styled distinctly
  // (animated, brand-coloured) so it reads as a loop, not a stray reversed
  // arrow.
  {
    id: DEBATE_LOOP_EDGE_ID,
    source: NODE_DEBATE_LOOP,
    target: NODE_CONTRARIAN,
    sourceHandle: "source-left",
    targetHandle: "target-left",
    label: "DEBATE_AGAIN (round 2)",
    animated: true,
    style: { stroke: "#7C3AED", strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#7C3AED" },
  },

  // -- debate_loop -> risk_officer (route_after_contrarian's PROCEED) ----
  {
    id: "debate-loop-to-risk",
    source: NODE_DEBATE_LOOP,
    target: NODE_RISK,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    label: "PROCEED",
    style: CONDITIONAL_EDGE_STYLE,
    markerEnd: ARROW,
  },

  // -- sequential tail: risk -> valuation -> portfolio -> memo -> pdf ----
  {
    id: "risk-to-valuation",
    source: NODE_RISK,
    target: NODE_VALUATION,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "valuation-to-portfolio-manager",
    source: NODE_VALUATION,
    target: NODE_PORTFOLIO_MANAGER,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "portfolio-manager-to-report-generator",
    source: NODE_PORTFOLIO_MANAGER,
    target: NODE_REPORT_GENERATOR,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "report-generator-to-pdf-export",
    source: NODE_REPORT_GENERATOR,
    target: NODE_PDF_EXPORT,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
  {
    id: "pdf-export-to-end",
    source: NODE_PDF_EXPORT,
    target: NODE_END,
    sourceHandle: "source-bottom",
    targetHandle: "target-top",
    markerEnd: ARROW,
  },
];
