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

export type AgentActivityState = "idle" | "thinking";

export interface ServiceInfo {
  port: number;
  rev: number;
}

export interface AgentInfo {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  services: Record<string, ServiceInfo>;
  startedAt?: string;
}

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
      type: "rate_limited";
      text: string;
      window: string | null;
      resets_at: number | null;
    })
  | (BaseEvent & {
      type: "notification";
      source: string;
      summary: string;
      notif_type?: string;
      sender?: string;
      fields?: Record<string, string>;
      decided?: "interrupt" | "snooze" | "trash";
      notif_id?: string;
    })
  | (BaseEvent & { type: "notification_cleared"; notif_id: string })
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
      type: "snapshot";
      state: AgentActivityState;
      chat: { events: VestaEvent[]; cursor: number | null };
      notifications: { pending: string[] };
    });

export type NotificationEvent = Extract<
  VestaEvent,
  { type: "notification" }
>;

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

export type ControlWsMessage =
  | { type: "hello"; version?: string; port?: number }
  | { type: "agents"; agents?: AgentInfo[] };

export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  hosted: boolean;
}

export interface ContextPreset {
  tokens: number;
  label: string;
  note: string;
  plans?: string[];
}

export interface ProviderContext {
  default: number;
  presets: ContextPreset[];
  defaults_by_plan?: Record<string, number>;
}

export interface ProviderEntry {
  display: string;
  models: string[] | "live";
  default_model: string | null;
  context: ProviderContext;
}

export interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

export interface Manifest {
  default_provider: string;
  default_personality: string;
  providers: Record<string, ProviderEntry>;
  personalities: Personality[];
}

export interface ProviderInfo {
  kind: "claude" | "openrouter" | "none";
  model: string | null;
  max_context_tokens: number | null;
  authed: boolean;
  plan: string | null;
}

export interface BackupInfo {
  id: string;
  agent_name: string;
  backup_type: string;
  created_at: string;
  size: number;
}

export interface UsageMeter {
  label: string;
  used_pct: number | null;
  resets_at: string | null;
}

export interface Usage {
  meters: UsageMeter[];
  credits: { used: number | null; limit: number | null } | null;
}

export interface FieldPredicate {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate?: boolean;
}

export interface NotificationInterruptRule {
  id: string;
  source?: string | null;
  type?: string | null;
  match?: FieldPredicate[];
  action: "interrupt" | "snooze" | "trash";
}

export interface FileTreeEntry {
  path: string;
  is_dir: boolean;
  mode: number;
}

export interface FileReadResponse {
  path: string;
  content: string;
  encoding: "utf-8" | "base64";
  readonly: boolean;
  mode: number;
  size: number;
  is_dir: boolean;
}

export interface SettingDef {
  key: string;
  type: "bool" | "number" | "select";
  label: string;
  description?: string;
  value: unknown;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  config?: SettingDef[];
  config_label?: string;
  options?: {
    value: string;
    label: string;
    preview?: string;
    custom?: boolean;
  }[];
}

export interface VoiceStatus {
  configured: boolean;
  provider: string | null;
  enabled?: boolean;
  settings?: SettingDef[];
}

export interface GatewayInfo {
  lan: { exposed: boolean; url: string | null };
  tunnel_url: string | null;
  port: number;
}

export interface GatewaySettings {
  auto_update: boolean;
  channel: ReleaseChannel;
  auto_backup: {
    enabled: boolean;
    hour: number;
    retention: { daily: number; weekly: number; monthly: number };
  };
}

export interface HostMount {
  host_path: string;
  container_path: string;
  writable: boolean;
}
