import type { SettingDef } from "../api/voice";

// How a number setting of the voice service reads on every client: a duration in milliseconds
// reads in seconds, and every other number shows two decimals.
export function formatSettingNumber(
  setting: SettingDef,
  value: number,
): string {
  if (setting.unit === "ms") return `${(value / 1000).toFixed(1)}s`;
  return value.toFixed(2);
}
