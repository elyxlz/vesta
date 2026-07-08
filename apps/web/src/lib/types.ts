export type AgentStatus =
  | "alive"
  | "starting"
  | "setting_up"
  | "not_authenticated"
  | "unprovisioned"
  | "restarting"
  | "stopped"
  | "dead"
  | "not_found";

export interface ServiceInfo {
  port: number;
  rev: number;
  // Per-service access key for the iframe URL path. Absent when talking to an
  // older vestad that predates key auth (the Dashboard falls back to the legacy
  // public path in that case).
  key?: string;
}

export interface AgentInfo {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  services: Record<string, ServiceInfo>;
  // Container start time (RFC3339), absent for an agent that has never started. Changes on every
  // restart, so it is the signal that clears a "restart to apply" flag (see use-restart-pending).
  startedAt?: string;
}

export type AgentActivityState = "idle" | "thinking";

export type InputMethod = "voice" | "typed";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & { type: "user"; text: string; input_method?: InputMethod })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "thinking"; text: string; signature: string })
  | (BaseEvent & { type: "chat"; text: string })
  | (BaseEvent & {
      type: "tool_start";
      tool: string;
      input: string;
      subagent?: boolean;
    })
  | (BaseEvent & { type: "tool_end"; tool: string; subagent?: boolean })
  | (BaseEvent & { type: "error"; text: string })
  | (BaseEvent & {
      type: "notification";
      source: string;
      summary: string;
      // Enriched fields (present on notifications emitted since the history feature shipped).
      notif_type?: string;
      sender?: string;
      fields?: Record<string, string>; // targetable structured extras, e.g. { chat_name: "Bride squad" }
      decided?: "interrupt" | "pool" | "trash"; // effective decision given the rules (trash = dropped)
      notif_id?: string; // file stem; pending while its file is on disk, cleared once processed
    })
  | (BaseEvent & {
      // Live broadcast-only delta: emitted when the agent processes a notification and deletes its
      // file. The view seeds pending from the connect snapshot, then removes this id when it arrives.
      type: "notification_cleared";
      notif_id: string;
    })
  | (BaseEvent & {
      type: "subagent_start";
      agent_id: string;
      agent_type: string;
    })
  | (BaseEvent & {
      type: "subagent_stop";
      agent_id: string;
      agent_type: string;
    })
  | (BaseEvent & {
      // The connect handshake: one event seeding a client with current agent state. Each domain
      // (chat, notifications, …) is its own object so new connect-time state extends without churn.
      type: "snapshot";
      state: AgentActivityState;
      chat: { events: VestaEvent[]; cursor: number | null };
      notifications: { pending: string[] };
    });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };

export type ReleaseChannel = "stable" | "beta";

export interface GatewayVersionInfo {
  version: string;
  api_compat: string;
  dev_mode: boolean;
  latest_version: string | null;
  update_available: boolean | null;
  branch?: string | null;
  channel?: ReleaseChannel;
  auto_update?: boolean;
}
