export interface AgentInfo {
  status: AgentStatus;
  id: string;
  authenticated: boolean;
  name: string;
  agent_ready: boolean;
  ws_port: number;
  alive: boolean;
  friendly_status: string;
}

export type AgentStatus = "running" | "stopped" | "dead" | "not_found" | "unknown";

export interface ListEntry {
  name: string;
  status: AgentStatus;
  authenticated: boolean;
  agent_ready: boolean;
  ws_port: number;
  alive: boolean;
  friendly_status: string;
}

export type AgentActivityState = "idle" | "thinking" | "tool_use";

export type OnboardingStep = "name" | "connect" | "creating" | "auth" | "done";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & { type: "user"; text: string })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "app_chat"; text: string })
  | (BaseEvent & { type: "tool_start"; tool: string; input: string })
  | (BaseEvent & { type: "tool_end"; tool: string })
  | (BaseEvent & { type: "error"; text: string })
  | (BaseEvent & { type: "notification"; source: string; summary: string })
  | (BaseEvent & { type: "history"; events: VestaEvent[]; state: AgentActivityState });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
