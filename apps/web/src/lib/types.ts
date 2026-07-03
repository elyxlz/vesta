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
}

export interface AgentInfo {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  services: Record<string, ServiceInfo>;
}

export type AgentActivityState = "idle" | "thinking";

export type InputMethod = "voice" | "typed";

type BaseEvent = { ts?: string };

export type VestaEvent =
  | (BaseEvent & { type: "status"; state: AgentActivityState })
  | (BaseEvent & { type: "user"; text: string; input_method?: InputMethod })
  | (BaseEvent & { type: "assistant"; text: string })
  | (BaseEvent & { type: "thinking"; text: string; signature: string })
  // Live streaming preview of an in-progress extended-thinking block. Broadcast-only (never in
  // history): accumulate for display, drop the buffer when the complete `thinking` event arrives.
  | (BaseEvent & { type: "thinking_delta"; text: string })
  | (BaseEvent & { type: "chat"; text: string })
  // Live chunk of the reply the agent is typing into `app-chat send`. Broadcast-only preview:
  // append to the draft (or replace it when reset), drop it when the real chat event arrives.
  | (BaseEvent & { type: "chat_delta"; text: string; reset: boolean })
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
      decided?: "interrupt" | "pool"; // effective decision given the rules
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
