import type {
  SettingDef,
  VoiceBehaviors,
  VoiceDomain,
  VoiceStatus,
} from "@vesta/core";
import type { SliderRange } from "@/components/ui/slider-math";

// Where a setting lives: a role's selected provider, or the behaviors every session shares.
export type SettingSection = VoiceDomain | "behavior";

const SETTING_SECTIONS: readonly SettingSection[] = [
  "stt",
  "tts",
  "judge",
  "behavior",
];

// What the voice page reads. The judge and the behaviors are null for an agent whose voice
// service has no such route.
export interface VoiceSettingsData {
  stt: VoiceStatus;
  tts: VoiceStatus;
  judge: VoiceStatus | null;
  behaviors: VoiceBehaviors | null;
}

// A select with more options than this opens the list screen; the system alert holds the rest.
export const ALERT_MAX_OPTIONS = 8;

type SettingOption = NonNullable<SettingDef["options"]>[number];

export function parseSettingSection(
  value: string | undefined,
): SettingSection | null {
  return SETTING_SECTIONS.find((section) => section === value) ?? null;
}

export function findSetting(
  data: VoiceSettingsData,
  section: SettingSection,
  key: string,
): SettingDef | null {
  const settings =
    section === "behavior" ? data.behaviors?.settings : data[section]?.settings;
  return settings?.find((setting) => setting.key === key) ?? null;
}

export function settingValue(setting: SettingDef): string {
  if (typeof setting.value === "string") return setting.value;
  if (typeof setting.value === "number") return String(setting.value);
  if (typeof setting.value === "boolean") return setting.value ? "on" : "off";
  return "default";
}

// The label of the chosen option, or the stored value when no option carries it.
export function selectedOptionLabel(setting: SettingDef): string {
  const chosen = setting.options?.find(
    (option) => option.value === setting.value,
  );
  return chosen?.label ?? settingValue(setting);
}

// The options whose label or description holds the query, in any letter case.
export function filterOptions(
  options: readonly SettingOption[],
  query: string,
): SettingOption[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...options];
  return options.filter(
    (option) =>
      option.label.toLowerCase().includes(needle) ||
      (option.description ?? "").toLowerCase().includes(needle),
  );
}

export function numberRange(setting: SettingDef): SliderRange {
  return {
    min: setting.min ?? 0,
    max: setting.max ?? 1,
    step: setting.step ?? 0.01,
  };
}

export function numberValue(setting: SettingDef): number {
  if (typeof setting.value === "number") return setting.value;
  if (typeof setting.default === "number") return setting.default;
  return numberRange(setting).min;
}

// A duration in milliseconds reads in seconds; every other number shows two decimals.
export function formatNumber(setting: SettingDef, value: number): string {
  if (setting.unit === "ms") return `${(value / 1000).toFixed(1)}s`;
  return value.toFixed(2);
}
