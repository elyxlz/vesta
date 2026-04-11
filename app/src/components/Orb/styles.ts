import type { AgentActivityState } from "@/lib/types";
import type { AgentOperation } from "@/stores/use-agent-ops";

export type OrbVisualState =
  | "loading"
  | "alive"
  | "thinking"
  | "booting"
  | "authenticating"
  | "stopping"
  | "starting"
  | "deleting"
  | "dead";

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
      return { label: "stopping...", orbState: "stopping" };
    case "starting":
      return { label: "starting...", orbState: "starting" };
    case "authenticating":
      return { label: "signing in...", orbState: "authenticating" };
    case "deleting":
      return { label: "deleting...", orbState: "deleting" };
    case "rebuilding":
      return { label: "rebuilding...", orbState: "starting" };
    case "backing-up":
      return { label: "backing up...", orbState: "alive" };
    case "restoring":
      return { label: "restoring...", orbState: "starting" };
  }

  if (!agent) return { label: "", orbState: "dead" };

  switch (agent.status) {
    case "alive":
      if (activityState === "thinking")
        return { label: "thinking", orbState: "thinking" };
      return { label: "alive", orbState: "alive" };
    case "starting":
      return { label: "waking up...", orbState: "booting" };
    case "not_authenticated":
      return { label: "not signed in", orbState: "authenticating" };
    case "restarting":
      return { label: "restarting...", orbState: "starting" };
    case "stopped":
      return { label: "stopped", orbState: "dead" };
    case "dead":
      return { label: "broken — delete and recreate", orbState: "dead" };
    default:
      return { label: agent.status, orbState: "dead" };
  }
}

export const orbColors: Record<OrbVisualState, [string, string, string]> = {
  loading: ["#e8cc8a", "#d4a84a", "#9e7e34"],
  alive: ["#b8ceb0", "#7a9e70", "#5a7e50"],
  thinking: ["#e8d0a0", "#c4a060", "#a08040"],
  booting: ["#c0d0e0", "#8a9eb0", "#6a8094"],
  authenticating: ["#90a8c8", "#5870a0", "#3a5080"],
  stopping: ["#c0d0e0", "#8a9eb0", "#6a8094"],
  starting: ["#c0d0e0", "#8a9eb0", "#6a8094"],
  deleting: ["#e0a0a0", "#c45050", "#a03030"],
  dead: ["#e0a0a0", "#c45050", "#a03030"],
};
