import type {
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderManifest,
  ProviderManifestEntry,
  ReleaseChannel,
} from "@vesta/core";

export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  hosted: boolean;
}

export type ContextPreset = ProviderContextPreset;
export type ProviderContext = ProviderContextPolicy;
export type ProviderEntry = ProviderManifestEntry;

export interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

export interface Manifest extends ProviderManifest {
  personalities: Personality[];
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
