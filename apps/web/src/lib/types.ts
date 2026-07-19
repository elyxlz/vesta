export type AgentStatus =
  | "alive"
  | "starting"
  | "setting_up"
  | "not_authenticated"
  | "unprovisioned"
  | "restarting"
  | "rebuilding"
  | "stopped"
  | "dead"
  | "not_found";

export interface ServiceInfo {
  port: number;
  rev: number;
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

interface BaseEvent {
  // The events.db rowid, present on every server-sent event; absent on client-only optimistic
  // bubbles (a locally-echoed send that has no persisted id until its append echo returns).
  id?: number;
  ts?: string;
}

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & {
      type: "user";
      text: string;
      input_method?: InputMethod;
      // The client-generated send-message id, echoed back on the append so the optimistic bubble
      // dedups by id (not text); `send_state` tracks a bubble whose POST is unconfirmed/failed.
      intent_id?: string;
      send_state?: "sending" | "retry" | "failed";
    })
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
      // A rejected Claude rate limit, from the SDK's structured classification (the agent never
      // relays the model's own paraphrase of which limit tripped).
      type: "rate_limited";
      text: string;
      window: string | null; // five_hour, seven_day, ... or null when unreported
      resets_at: number | null; // unix seconds the window resets at, when reported
    })
  | (BaseEvent & {
      type: "notification";
      source: string;
      summary: string;
      // Enriched fields (present on notifications emitted since the history feature shipped).
      notif_type?: string;
      sender?: string;
      fields?: Record<string, string>; // targetable structured extras, e.g. { chat_name: "Bride squad" }
      decided?: "interrupt" | "snooze" | "trash"; // effective decision given the rules (trash = dropped)
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
      config: { timezone: string };
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

// The gateway control WS's own frames (distinct from the per-agent VestaEvent stream): a version
// handshake on connect, then agent-list snapshots on every roster change.
export type ControlWsMessage =
  | { type: "hello"; version?: string; port?: number }
  | { type: "agents"; agents?: AgentInfo[] };
