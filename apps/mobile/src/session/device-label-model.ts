import type { ReleaseChannel } from "@vesta/core";

export function titleCaseChannel(channel: ReleaseChannel | undefined): string {
  if (!channel) return "unknown";
  return channel === "beta" ? "Beta" : "Stable";
}

export function lastSeenLabel(lastSeen: string): string {
  const then = new Date(lastSeen).getTime();
  if (Number.isNaN(then)) return "last seen recently";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${String(mins)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${String(hours)}h ago`;
  return `${String(Math.floor(hours / 24))}d ago`;
}
