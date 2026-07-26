import {
  agentOrbState,
  type AgentActivityState,
  type AgentStatus,
  type OrbVisualState,
} from "@vesta/core";
import type { AgentOperation } from "@/stores/use-agent-ops";
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

  const orbState = agentOrbState(agent.status, activityState);
  return { label: statusLabel(agent.status, orbState), orbState };
}

function statusLabel(status: AgentStatus, orbState: OrbVisualState): string {
  switch (status) {
    case "alive":
      return orbState === "thinking" ? "thinking" : "alive";
    case "starting":
      return "waking up...";
    case "setting_up":
      return "setting up...";
    case "not_authenticated":
      return "needs you to sign in again";
    case "unprovisioned":
      return "needs to be set up";
    case "restarting":
      return "restarting...";
    case "rebuilding":
      return "updating...";
    case "stopped":
      return "stopped";
    case "dead":
      return "broken, delete and recreate it in settings";
    case "not_found":
      return "unavailable";
  }
}
