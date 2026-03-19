export interface BoxInfo {
  status: BoxStatus;
  id: string;
  authenticated: boolean;
  name: string;
  agent_ready: boolean;
  ws_port: number;
  alive: boolean;
  friendly_status: string;
}

export type BoxStatus = "running" | "stopped" | "dead" | "not_found" | "unknown";

export interface ListEntry {
  name: string;
  status: BoxStatus;
  authenticated: boolean;
  agent_ready: boolean;
  ws_port: number;
  alive: boolean;
  friendly_status: string;
}

export interface PlatformStatus {
  ready: boolean;
  platform: string;
  wsl_installed: boolean;
  virtualization_enabled: boolean | null;
  distro_registered: boolean;
  distro_healthy: boolean;
  services_ready: boolean;
  needs_reboot: boolean;
  message: string;
}

export type BoxActivityState = "idle" | "thinking" | "tool_use";

export type OnboardingStep = "platform" | "name" | "creating" | "auth" | "done";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: BoxActivityState })
  | (BaseEvent & { type: "user"; text: string })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "tool_start"; tool: string; input: string })
  | (BaseEvent & { type: "tool_end"; tool: string })
  | (BaseEvent & { type: "error"; text: string })
  | (BaseEvent & { type: "notification"; source: string; summary: string })
  | (BaseEvent & { type: "history"; events: VestaEvent[]; state: BoxActivityState });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
