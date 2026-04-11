
export type AgentStatus =
  | "alive"
  | "starting"
  | "not_authenticated"
  | "restarting"
  | "stopped"
  | "dead"
  | "not_found";

export interface AgentInfo {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  services: Record<string, number>;
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
  | (BaseEvent & {
      type: "history";
      events: VestaEvent[];
      state: AgentActivityState;
      cursor: number | null;
    });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };
