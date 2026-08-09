// frontend/src/lib/graph/pipelineNodeStyles.ts
// AIRP -- shared visual tokens for the pipeline graph's node renderers
// (T-094's PipelineGraphNode, T-096's LiveGraphNode)
//
// Extracted out of PipelineGraphNode.tsx (T-094) rather than duplicated
// when LiveGraphNode.tsx (T-096) needed the exact same colour-by-kind
// treatment plus its own live-status layer on top -- both node
// components render the same underlying "what kind of pipeline step is
// this" card, coloured by docs/AIRP_Architecture.drawio's own legend
// (research agents blue, decision agents red, portfolio manager green);
// only T-096's node additionally overlays a status ring/badge. A single
// source of truth here means a future palette tweak never needs to be
// applied in two places and risk drifting apart.

import { type PipelineNodeKind } from "@/lib/graph/pipelineTopology";

export const PIPELINE_KIND_STYLES: Record<PipelineNodeKind, string> = {
  boundary: "border-line bg-canvas text-muted",
  planner: "border-brand-700 bg-brand-500 text-white",
  research: "border-blue-900 bg-blue-700 text-white",
  routing: "border-slate-700 bg-slate-500 text-white",
  decision: "border-red-800 bg-verdict-sell text-white",
  synthesis: "border-emerald-800 bg-verdict-buy text-white",
  output: "border-emerald-900 bg-emerald-800 text-white",
};

/** Shared handle styling -- small, low-contrast dots that don't compete visually with node text. */
export const PIPELINE_HANDLE_CLASS_NAME = "!h-2 !w-2 !border-none !bg-ink/30";
