const SECTIONS = [
  { key: "general", title: "General" },
  { key: "provider", title: "Provider and model" },
  { key: "voice", title: "Voice" },
  { key: "notifications", title: "Notification rules" },
  { key: "files", title: "Files" },
  { key: "host-access", title: "Host access" },
  { key: "backups", title: "Backups" },
] as const;

export type AgentSettingsSectionKey = (typeof SECTIONS)[number]["key"];

export interface AgentSettingsSection {
  key: AgentSettingsSectionKey;
  title: string;
}

export const AGENT_SETTINGS_SECTIONS: readonly AgentSettingsSection[] =
  SECTIONS;

export function sectionTitle(key: string): string {
  return findSection(key)?.title ?? "Settings";
}

// Carrying the found section lets a caller index a Record<AgentSettingsSectionKey, ...>
// without re-deriving which keys exist; an unknown deep-link key returns null.
export function findSection(key: string): AgentSettingsSection | null {
  return AGENT_SETTINGS_SECTIONS.find((entry) => entry.key === key) ?? null;
}
