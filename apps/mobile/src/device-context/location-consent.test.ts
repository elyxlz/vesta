import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestLocationSharing } from "./location-consent";

const os = vi.hoisted(() => ({
  foregroundGranted: true,
  calls: [] as string[],
}));
vi.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: () => {
    os.calls.push("foreground");
    return Promise.resolve({ granted: os.foregroundGranted });
  },
  requestBackgroundPermissionsAsync: () => {
    os.calls.push("background");
    return Promise.resolve({ granted: false });
  },
}));

describe("requestLocationSharing", () => {
  beforeEach(() => {
    os.calls = [];
    os.foregroundGranted = true;
  });

  it("asks when-in-use then always-on, and turns on even when always-on is declined", async () => {
    await expect(requestLocationSharing()).resolves.toBe(true);
    expect(os.calls).toEqual(["foreground", "background"]);
  });

  it("stops at a refused when-in-use grant", async () => {
    os.foregroundGranted = false;
    await expect(requestLocationSharing()).resolves.toBe(false);
    expect(os.calls).toEqual(["foreground"]);
  });
});
