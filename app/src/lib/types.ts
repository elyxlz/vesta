export interface AgentInfo {
  status: AgentStatus;
  id: string;
}

export type AgentStatus = "Running" | "Stopped" | "NotFound" | "Unknown";

export type ChatEvent =
  | { kind: "Attached" }
  | { kind: "Output"; text: string }
  | { kind: "Detached" }
  | { kind: "Error"; message: string };

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };

export type AuthEvent =
  | { kind: "Output"; text: string }
  | { kind: "UrlDetected"; url: string }
  | { kind: "Complete" }
  | { kind: "Error"; message: string };
