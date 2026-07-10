import type { AgentActivityState } from "@/lib/types";
import type { AgentOperation } from "@/stores/use-agent-ops";

export type OrbVisualState = "alive" | "thinking" | "busy" | "off" | "deleting";

interface AgentLike {
  status: string;
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
    case "rebuilding":
      return { label: "rebuilding...", orbState: "busy" };
    case "backing-up":
      return { label: "backing up...", orbState: "alive" };
    case "restoring":
      return { label: "restoring...", orbState: "busy" };
  }

  if (!agent) return { label: "", orbState: "off" };

  switch (agent.status) {
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
    case "stopped":
      return { label: "stopped", orbState: "off" };
    case "dead":
      return {
        label: "broken, delete and recreate it in settings",
        orbState: "off",
      };
    default:
      return { label: agent.status, orbState: "off" };
  }
}

export const orbColors: Record<OrbVisualState, [string, string, string]> = {
  alive: ["#b8ceb0", "#7a9e70", "#5a7e50"],
  thinking: ["#e8d0a0", "#c4a060", "#a08040"],
  busy: ["#c0d0e0", "#8a9eb0", "#6a8094"],
  off: ["#c2c0ba", "#8e8c84", "#66645e"],
  deleting: ["#e0a0a0", "#c45050", "#a03030"],
};
