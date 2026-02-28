export interface AgentInfo {
  status: AgentStatus;
  id: string;
  authenticated: boolean;
}

export type AgentStatus = "Running" | "Stopped" | "NotFound" | "Unknown";

export type ChatEvent =
  | { kind: "Attached" }
  | { kind: "Output"; text: string }
  | { kind: "Detached" };

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
