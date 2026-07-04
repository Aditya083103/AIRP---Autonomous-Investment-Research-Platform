// frontend/src/components/results/AgentWeightsPanel.tsx
// AIRP -- Agent weights panel (T-061)
//
// Renders InvestmentDecisionResponse.agent_weights -- how much weight
// (0.0-1.0) the Portfolio Manager assigned to each committee member's
// output when forming the verdict. Reuses the existing ProgressBar
// primitive (T-054) rather than introducing a chart-library bar chart:
// a weight is conceptually identical to the "N% complete" value
// ProgressBar already renders, just interpreted as "N% of the
// decision's evidence" instead of "N% of the pipeline finished".
//
// Display names come from lib/agentProgress.ts's COMMITTEE_ROSTER --
// the same lookup AgentProgressBoard and DebateViewer use -- so a
// weight key like "fundamental_analyst" renders as "Fundamental
// Analyst" consistently everywhere in the app, instead of this panel
// inventing its own snake_case-to-title-case formatting that could
// drift from the roster's actual display names.

import { Card, ProgressBar } from "@/components/ui";
import { COMMITTEE_ROSTER } from "@/lib/agentProgress";

export interface AgentWeightsPanelProps {
  agentWeights: Record<string, number>;
}

function displayNameFor(agentName: string): string {
  const rosterEntry = COMMITTEE_ROSTER.find((entry) => entry.nodeName === agentName);
  if (rosterEntry) {
    return rosterEntry.displayName;
  }
  // Fallback for any agent_name not on the roster (should not happen in
  // practice -- agent_weights keys are always committee agent_name
  // values -- but a readable fallback beats a raw snake_case string).
  return agentName
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Renders how much weight the Portfolio Manager assigned to each agent's output. */
export function AgentWeightsPanel({ agentWeights }: AgentWeightsPanelProps): JSX.Element {
  const entries = Object.entries(agentWeights).sort(([, a], [, b]) => b - a);

  return (
    <Card data-testid="agent-weights-panel">
      <Card.Header>
        <Card.Title>{"How the committee's evidence was weighted"}</Card.Title>
      </Card.Header>
      {entries.length === 0 ? (
        <p className="text-sm text-muted">No agent weighting data was recorded.</p>
      ) : (
        <div className="space-y-3">
          {entries.map(([agentName, weight]) => (
            <ProgressBar
              key={agentName}
              value={Math.round(weight * 100)}
              label={displayNameFor(agentName)}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
