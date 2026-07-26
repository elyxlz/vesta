import {
  agentOrbState,
  agentStatusLabel,
  type AgentActivityState,
  type AgentStatus,
  type OrbVisualState,
} from "@vesta/core";
import { getOpLabel, type AgentOperation } from "@/stores/use-agent-ops";
export { orbColors } from "@/design-tokens";
export type { OrbVisualState };

interface AgentLike {
  status: AgentStatus;
}

export function getAgentVisualStatus(
  agent: AgentLike | null,
  operation: AgentOperation,
  error: string,
  activityState: AgentActivityState,
): { label: string; orbState: OrbVisualState } {
  const { label, orbState } = resolveStatus(agent, operation, activityState);
  return { label: error || label, orbState };
}

function resolveStatus(
  agent: AgentLike | null,
  operation: AgentOperation,
  activityState: AgentActivityState,
): { label: string; orbState: OrbVisualState } {
  if (operation !== "idle") {
    return {
      label: getOpLabel(operation),
      orbState: operationOrbState(operation),
    };
  }

  if (!agent) return { label: "", orbState: "off" };

  return {
    label: agentStatusLabel(agent.status, activityState),
    orbState: agentOrbState(agent.status, activityState),
  };
}

// A backup runs against a live agent, so it keeps the alive orb; everything else in flight reads as
// work in progress.
function operationOrbState(
  operation: Exclude<AgentOperation, "idle">,
): OrbVisualState {
  switch (operation) {
    case "deleting":
      return "deleting";
    case "backing-up":
      return "alive";
    case "stopping":
    case "starting":
    case "authenticating":
    case "restoring":
      return "busy";
  }
}
