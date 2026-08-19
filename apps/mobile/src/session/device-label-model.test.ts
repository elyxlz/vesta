import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { lastSeenLabel, titleCaseChannel } from "./device-label-model";

const NOW = new Date("2026-08-17T12:00:00Z");
const MINUTE_MS = 60_000;

function seenAgo(minutes: number): string {
  return new Date(NOW.getTime() - minutes * MINUTE_MS).toISOString();
}

describe("lastSeenLabel", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    [0.5, "just now"],
    [59, "59m ago"],
    [60, "1h ago"],
    [5 * 60, "5h ago"],
    [3 * 24 * 60, "3d ago"],
  ])("labels a device seen %s minutes ago as %s", (minutes, label) => {
    expect(lastSeenLabel(seenAgo(minutes))).toBe(label);
  });

  it("labels an unparseable timestamp as seen recently", () => {
    expect(lastSeenLabel("not-a-timestamp")).toBe("last seen recently");
  });
});

describe("titleCaseChannel", () => {
  it.each([
    ["stable", "Stable"],
    ["beta", "Beta"],
  ] as const)("title-cases %s as %s", (channel, label) => {
    expect(titleCaseChannel(channel)).toBe(label);
  });

  it("answers unknown while the settings have not loaded", () => {
    expect(titleCaseChannel(undefined)).toBe("unknown");
  });
});
