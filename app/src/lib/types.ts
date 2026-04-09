import type { Dispatch, SetStateAction } from "react";

export interface AgentHomeOutletContext {
  chatCollapsed: boolean;
  setChatCollapsed: Dispatch<SetStateAction<boolean>>;
}

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

export type AgentActivityState = "idle" | "thinking";

export type OnboardingStep = "name" | "connect" | "creating" | "auth" | "done";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & { type: "user"; text: string })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "thinking"; text: string; signature: string })
  | (BaseEvent & { type: "chat"; text: string })
  | (BaseEvent & { type: "tool_start"; tool: string; input: string })
  | (BaseEvent & { type: "tool_end"; tool: string })
  | (BaseEvent & { type: "error"; text: string })
  | (BaseEvent & { type: "notification"; source: string; summary: string })
  | (BaseEvent & { type: "service_update"; service: string; action: "registered" | "updated" | "removed" })
  | (BaseEvent & { type: "history"; events: VestaEvent[]; state: AgentActivityState; cursor: number | null });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
