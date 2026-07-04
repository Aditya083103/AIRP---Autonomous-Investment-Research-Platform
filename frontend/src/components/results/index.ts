// frontend/src/components/results/index.ts
// Barrel export for the T-061 Analysis Results components. Mirrors the
// pattern already used by src/components/ui/index.ts and
// src/components/landing/index.ts.

export {
  AgentWeightsPanel,
  type AgentWeightsPanelProps,
} from "@/components/results/AgentWeightsPanel";
export { BullBearPanel, type BullBearPanelProps } from "@/components/results/BullBearPanel";
export { ConvictionGauge, type ConvictionGaugeProps } from "@/components/results/ConvictionGauge";
export { KeyRisksList, type KeyRisksListProps } from "@/components/results/KeyRisksList";
export { MemoSection, type MemoSectionProps } from "@/components/results/MemoSection";
export { ResultsPanel, type ResultsPanelProps } from "@/components/results/ResultsPanel";
export { VerdictPanel, type VerdictPanelProps } from "@/components/results/VerdictPanel";
