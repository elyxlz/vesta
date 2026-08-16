import { beforeEach, describe, expect, it, vi } from "vitest";
import { locationUndecided, requestLocationSharing } from "./location-consent";

const os = vi.hoisted(() => ({
  foregroundGranted: true,
  status: "undetermined",
  calls: [] as string[],
}));
vi.mock("expo-location", () => ({
  PermissionStatus: {
    UNDETERMINED: "undetermined",
    GRANTED: "granted",
    DENIED: "denied",
  },
  requestForegroundPermissionsAsync: () => {
    os.calls.push("foreground");
    return Promise.resolve({ granted: os.foregroundGranted });
  },
  requestBackgroundPermissionsAsync: () => {
    os.calls.push("background");
    return Promise.resolve({ granted: false });
  },
  getForegroundPermissionsAsync: () => Promise.resolve({ status: os.status }),
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

describe("locationUndecided", () => {
  it("is true only while the OS has never been asked", async () => {
    os.status = "undetermined";
    await expect(locationUndecided()).resolves.toBe(true);
    os.status = "granted";
    await expect(locationUndecided()).resolves.toBe(false);
    os.status = "denied";
    await expect(locationUndecided()).resolves.toBe(false);
  });
});
