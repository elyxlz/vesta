import {
  agentOrbState,
  agentStatusLabel,
  type AgentActivityState,
  type AgentOperation as ServerOperation,
  type AgentStatus,
  type ModelAccess,
  type OrbVisualState,
} from "@vesta/core";
import { getOpLabel, type AgentRequest } from "@/stores/use-agent-ops";
export { orbColors } from "@/design-tokens";

interface AgentLike {
  status: AgentStatus;
  modelAccess?: ModelAccess;
  operation: ServerOperation | null;
}

export function getAgentVisualStatus(
  agent: AgentLike | null,
  operation: AgentRequest,
  error: string,
  activityState: AgentActivityState,
): { label: string; orbState: OrbVisualState } {
  const { label, orbState } = resolveStatus(agent, operation, activityState);
  return { label: error || label, orbState };
}

function resolveStatus(
  agent: AgentLike | null,
  operation: AgentRequest,
  activityState: AgentActivityState,
): { label: string; orbState: OrbVisualState } {
  if (operation !== "idle") {
    return {
      label: getOpLabel(operation),
      orbState: operationOrbState(operation),
    };
  }

  if (!agent) return { label: "", orbState: "off" };

  if (agent.status === "alive" && agent.modelAccess?.state === "cooling_down") {
    const until = new Date(agent.modelAccess.until * 1000).toLocaleTimeString(
      [],
      {
        hour: "numeric",
        minute: "2-digit",
      },
    );
    return { label: `rate limited until ${until}`, orbState: "busy" };
  }
  return {
    label: agentStatusLabel(agent.status, activityState, agent.operation),
    orbState: agentOrbState(agent.status, activityState, agent.operation),
  };
}

function operationOrbState(
  operation: Exclude<AgentRequest, "idle">,
): OrbVisualState {
  switch (operation) {
    case "deleting":
      return "deleting";
    case "stopping":
    case "starting":
    case "authenticating":
    case "backing-up":
    case "restoring":
      return "busy";
  }
}
