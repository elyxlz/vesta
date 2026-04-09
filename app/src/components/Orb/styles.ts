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

export function getOrbVisualState(
  status: string,
  authenticated: boolean,
  agentReady: boolean,
  activityState: AgentActivityState,
  operation: AgentOperation,
): OrbVisualState {
  if (operation === "deleting") return "deleting";
  if (operation === "stopping") return "stopping";
  if (operation === "starting") return "starting";
  if (operation === "authenticating") return "authenticating";

  if (status === "running") {
    if (!authenticated) return "authenticating";
    if (!agentReady) return "booting";
    if (activityState === "thinking") return "thinking";
    return "alive";
  }

  return "dead";
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
