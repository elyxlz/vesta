export interface AgentInfo {
  status: AgentStatus;
  id: string;
  authenticated: boolean;
  name: string;
  agent_ready: boolean;
  ws_port: number;
}

export type AgentStatus = "running" | "stopped" | "dead" | "not_found" | "unknown";

export interface ListEntry {
  name: string;
  status: AgentStatus;
  authenticated: boolean;
  agent_ready: boolean;
  ws_port: number;
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

export type AgentActivityState = "idle" | "thinking" | "tool_use";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & { type: "user"; text: string })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "tool_start"; tool: string; input: string })
  | (BaseEvent & { type: "tool_end"; tool: string })
  | (BaseEvent & { type: "error"; text: string })
  | (BaseEvent & { type: "notification"; source: string; summary: string })
  | (BaseEvent & { type: "history"; events: VestaEvent[]; state: AgentActivityState });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
