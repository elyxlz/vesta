import type { AgentActivityState, ModelAccess } from "@vesta/core";
import type { AgentOperation } from "@/stores/use-agent-ops";
export { orbColors } from "@/design-tokens";

export type OrbVisualState = "alive" | "thinking" | "busy" | "off" | "deleting";

interface AgentLike {
  status: string;
  modelAccess?: ModelAccess;
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
  switch (operation) {
    case "stopping":
      return { label: "stopping...", orbState: "busy" };
    case "starting":
      return { label: "starting...", orbState: "busy" };
    case "authenticating":
      return { label: "signing in...", orbState: "busy" };
    case "deleting":
      return { label: "deleting...", orbState: "deleting" };
    case "backing-up":
      return { label: "backing up...", orbState: "alive" };
    case "restoring":
      return { label: "restoring...", orbState: "busy" };
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
  return resolveAgentStatus(agent.status, activityState);
}

function resolveAgentStatus(
  status: string,
  activityState: AgentActivityState,
): { label: string; orbState: OrbVisualState } {
  switch (status) {
    case "alive":
      if (activityState === "thinking")
        return { label: "thinking", orbState: "thinking" };
      return { label: "alive", orbState: "alive" };
    case "starting":
      return { label: "waking up...", orbState: "busy" };
    case "setting_up":
      return { label: "setting up...", orbState: "busy" };
    case "not_authenticated":
      return { label: "needs to sign in again", orbState: "busy" };
    case "unprovisioned":
      return { label: "not set up", orbState: "busy" };
    case "restarting":
      return { label: "restarting...", orbState: "busy" };
    case "rebuilding":
      return { label: "updating...", orbState: "busy" };
    case "stopped":
      return { label: "stopped", orbState: "off" };
    case "dead":
      return {
        label: "broken, delete and recreate it in settings",
        orbState: "off",
      };
    default:
      return { label: status, orbState: "off" };
  }
}
