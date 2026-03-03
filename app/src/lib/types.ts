export interface AgentInfo {
  status: AgentStatus;
  id: string;
  authenticated: boolean;
}

export type AgentStatus = "running" | "stopped" | "not_found" | "unknown";

export type AgentActivityState = "idle" | "thinking" | "tool_use";

export type VestaEvent =
  | { type: "status"; state: AgentActivityState }
  | { type: "user"; text: string }
  | { type: "assistant"; text: string }
  | { type: "tool_start"; tool: string; input: string }
  | { type: "tool_end"; tool: string }
  | { type: "error"; text: string }
  | { type: "notification"; source: string; summary: string }
  | { type: "history"; events: VestaEvent[]; state: AgentActivityState };

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
