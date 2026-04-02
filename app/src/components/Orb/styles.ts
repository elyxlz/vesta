import type { AgentActivityState } from "@/lib/types";
import type { AgentOperation } from "@/stores/use-agent-ops";

export type OrbVisualState =
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
    if (activityState === "thinking" || activityState === "tool_use")
      return "thinking";
    return "alive";
  }

  return "dead";
}

export const orbColors: Record<OrbVisualState, [string, string, string]> = {
  alive: ["#b8ceb0", "#7a9e70", "#5a7e50"],
  thinking: ["#e8d0a0", "#c4a060", "#a08040"],
  booting: ["#c4deb8", "#8ab880", "#6a9e5a"],
  authenticating: ["#c0d0e8", "#80a0c4", "#6080a4"],
  stopping: ["#c4bdb5", "#a09890", "#8b7e74"],
  starting: ["#c4deb8", "#8ab880", "#6a9e5a"],
  deleting: ["#c4bdb5", "#a09890", "#8b7e74"],
  dead: ["#c4bdb5", "#a09890", "#8b7e74"],
};

export function getOrbClasses(state: OrbVisualState): {
  float: string;
  glow: string;
  breathe: string;
  body: string;
} {
  switch (state) {
    case "alive":
      return {
        float: "animate-float",
        glow: "animate-glow-pulse",
        breathe: "animate-orb-breathe",
        body: "",
      };
    case "thinking":
      return {
        float: "animate-float-fast",
        glow: "animate-glow-pulse-fast",
        breathe: "animate-orb-breathe-fast",
        body: "",
      };
    case "booting":
      return {
        float: "animate-float-medium",
        glow: "animate-glow-swell",
        breathe: "animate-orb-breathe",
        body: "",
      };
    case "authenticating":
      return {
        float: "animate-float-medium",
        glow: "animate-glow-pulse",
        breathe: "animate-orb-breathe",
        body: "",
      };
    case "stopping":
      return {
        float: "",
        glow: "animate-glow-fade",
        breathe: "",
        body: "animate-orb-wind-down",
      };
    case "starting":
      return {
        float: "",
        glow: "animate-glow-swell-fast",
        breathe: "",
        body: "animate-orb-wake-up",
      };
    case "deleting":
      return {
        float: "",
        glow: "animate-glow-fade",
        breathe: "",
        body: "animate-shrink-away",
      };
    case "dead":
      return {
        float: "",
        glow: "",
        breathe: "",
        body: "scale-[0.92]",
      };
  }
}
