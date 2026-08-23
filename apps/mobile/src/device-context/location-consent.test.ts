import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  requestLocationIfUndecided,
  requestLocationSharing,
} from "./location-consent";

const os = vi.hoisted(() => ({
  foregroundGranted: true,
  backgroundGranted: false,
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
    return Promise.resolve({ granted: os.backgroundGranted });
  },
  getForegroundPermissionsAsync: () => Promise.resolve({ status: os.status }),
}));

describe("requestLocationSharing", () => {
  beforeEach(() => {
    os.calls = [];
    os.foregroundGranted = true;
    os.backgroundGranted = false;
  });

  it("asks when-in-use then always-on, and reports a declined always-on", async () => {
    await expect(requestLocationSharing()).resolves.toBe("when-in-use");
    expect(os.calls).toEqual(["foreground", "background"]);
  });

  it("reports the always-on grant", async () => {
    os.backgroundGranted = true;
    await expect(requestLocationSharing()).resolves.toBe("always");
  });

  it("stops at a refused when-in-use grant", async () => {
    os.foregroundGranted = false;
    await expect(requestLocationSharing()).resolves.toBe("denied");
    expect(os.calls).toEqual(["foreground"]);
  });
});

describe("requestLocationIfUndecided", () => {
  beforeEach(() => {
    os.calls = [];
    os.foregroundGranted = true;
  });

  it("asks only a phone the OS has never asked", async () => {
    os.status = "undetermined";
    await requestLocationIfUndecided();
    expect(os.calls).toEqual(["foreground", "background"]);
  });

  it("keeps a phone's earlier answer, granted or refused", async () => {
    for (const status of ["granted", "denied"]) {
      os.status = status;
      os.calls = [];
      await requestLocationIfUndecided();
      expect(os.calls).toEqual([]);
    }
  });
});
