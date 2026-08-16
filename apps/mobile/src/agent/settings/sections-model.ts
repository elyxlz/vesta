export interface AgentSettingsSection {
  key: string;
  title: string;
  advanced: boolean;
}

export const AGENT_SETTINGS_SECTIONS: readonly AgentSettingsSection[] = [
  { key: "general", title: "General", advanced: false },
  { key: "provider", title: "Provider and model", advanced: true },
  { key: "voice", title: "Voice", advanced: true },
  { key: "notifications", title: "Notification rules", advanced: true },
  { key: "files", title: "Files", advanced: true },
  { key: "host-access", title: "Host access", advanced: true },
  { key: "backups", title: "Backups", advanced: true },
];

// Agent settings on Android carry only the simple critical controls, so a
// deep link into a hidden section lands on the fallback, never a broken page.
export function showsAdvancedSections(
  os: string | undefined = process.env.EXPO_OS,
): boolean {
  return os === "ios";
}

export function sectionTitle(key: string): string {
  const section = AGENT_SETTINGS_SECTIONS.find((entry) => entry.key === key);
  return section?.title ?? "Settings";
}

export type SectionAvailability = "available" | "hidden" | "unknown";

export function sectionAvailability(
  key: string,
  os: string | undefined = process.env.EXPO_OS,
): SectionAvailability {
  const section = AGENT_SETTINGS_SECTIONS.find((entry) => entry.key === key);
  if (!section) return "unknown";
  if (section.advanced && !showsAdvancedSections(os)) return "hidden";
  return "available";
}
