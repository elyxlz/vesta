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
  alive: boolean;
  status: string;
  authenticated: boolean;
  agent_ready: boolean;
  friendly_status: string;
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

  if (agent.alive) {
    if (activityState === "thinking")
      return { label: "thinking", orbState: "thinking" };
    return { label: "alive", orbState: "alive" };
  }

  if (agent.status === "running" && agent.authenticated && !agent.agent_ready)
    return { label: "waking up...", orbState: "booting" };
  if (agent.status === "running" && !agent.authenticated)
    return { label: "not signed in", orbState: "authenticating" };
  if (agent.status === "stopped")
    return { label: "stopped", orbState: "dead" };
  if (agent.status === "dead")
    return { label: "broken — delete and recreate", orbState: "dead" };

  return { label: agent.friendly_status || agent.status, orbState: "dead" };
}

export const orbColors: Record<OrbVisualState, [string, string, string]> = {
  loading: ["#e8cc8a", "#d4a84a", "#9e7e34"],
  alive: ["#b8ceb0", "#7a9e70", "#5a7e50"],
  thinking: ["#e8d0a0", "#c4a060", "#a08040"],
  booting: ["#c4deb8", "#8ab880", "#6a9e5a"],
  authenticating: ["#c0d0e8", "#80a0c4", "#6080a4"],
  stopping: ["#c4bdb5", "#a09890", "#8b7e74"],
  starting: ["#c4deb8", "#8ab880", "#6a9e5a"],
  deleting: ["#c4bdb5", "#a09890", "#8b7e74"],
  dead: ["#c4bdb5", "#a09890", "#8b7e74"],
};
