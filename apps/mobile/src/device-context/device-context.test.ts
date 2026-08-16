import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  FRESH_FIX_TIMEOUT_MS,
  LAST_KNOWN_FIX_MAX_AGE_MS,
  readDeviceContext,
  toDevicePosition,
} from "./device-context";

const location = vi.hoisted(() => ({
  granted: true,
  backgroundGranted: false,
  permissionThrows: false,
  // A fresh fix that never settles (indoors, no satellites).
  pending: false,
  current: null as {
    coords: { latitude: number; longitude: number; accuracy: number | null };
  } | null,
  last: null as {
    coords: { latitude: number; longitude: number; accuracy: number | null };
  } | null,
  lastOptions: undefined as unknown,
  geocoded: [] as {
    city: string | null;
    region: string | null;
    country: string | null;
  }[],
  calls: [] as string[],
}));
vi.mock("expo-localization", () => ({
  getCalendars: () => [{ timeZone: "Asia/Tokyo" }],
}));
vi.mock("expo-location", () => ({
  Accuracy: { Low: 1, Balanced: 3 },
  getForegroundPermissionsAsync: () =>
    location.permissionThrows
      ? Promise.reject(new Error("no native module"))
      : Promise.resolve({ granted: location.granted }),
  getBackgroundPermissionsAsync: () =>
    Promise.resolve({ granted: location.backgroundGranted }),
  getCurrentPositionAsync: (options: { accuracy: number }) => {
    location.calls.push(`current:${String(options.accuracy)}`);
    return location.pending
      ? new Promise(() => undefined)
      : Promise.resolve(location.current);
  },
  getLastKnownPositionAsync: (options: unknown) => {
    location.calls.push("last");
    location.lastOptions = options;
    return Promise.resolve(location.last);
  },
  reverseGeocodeAsync: () => Promise.resolve(location.geocoded),
}));

const tokyo = {
  coords: { latitude: 35.6762, longitude: 139.6503, accuracy: 50 },
};

describe("toDevicePosition", () => {
  it("carries the fix and the macro place", () => {
    expect(
      toDevicePosition(
        { latitude: 1, longitude: 2, accuracy: 10 },
        { city: "Tokyo", region: null, country: "Japan" },
      ),
    ).toEqual({
      latitude: 1,
      longitude: 2,
      accuracyM: 10,
      place: { city: "Tokyo", region: null, country: "Japan" },
    });
  });

  it("drops an empty place", () => {
    expect(
      toDevicePosition(
        { latitude: 1, longitude: 2, accuracy: null },
        { city: null, region: null, country: null },
      ),
    ).toEqual({ latitude: 1, longitude: 2, accuracyM: null, place: null });
    expect(
      toDevicePosition({ latitude: 1, longitude: 2, accuracy: null }, null)
        .place,
    ).toBeNull();
  });
});

describe("readDeviceContext", () => {
  beforeEach(() => {
    location.granted = true;
    location.backgroundGranted = false;
    location.current = tokyo;
    location.last = tokyo;
    location.geocoded = [{ city: "Tokyo", region: null, country: "Japan" }];
    location.calls = [];
  });

  it("retracts the position when location is not shared", async () => {
    await expect(
      readDeviceContext({ shareLocation: false, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Asia/Tokyo",
      position: null,
    });
    expect(location.calls).toEqual([]);
  });

  it("gives up on a fresh fix that never arrives and reports the zone alone", async () => {
    vi.useFakeTimers();
    try {
      location.pending = true;
      const report = readDeviceContext({
        shareLocation: true,
        mode: "foreground",
      });
      await vi.advanceTimersByTimeAsync(FRESH_FIX_TIMEOUT_MS);
      await expect(report).resolves.toEqual({ timezone: "Asia/Tokyo" });
    } finally {
      location.pending = false;
      vi.useRealTimers();
    }
  });

  it("takes a low-power fresh fix in the background when location is allowed always", async () => {
    location.backgroundGranted = true;
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.calls).toEqual(["current:1"]);
    // No fresh fix in time: the last known one is the fallback.
    location.calls = [];
    location.current = null;
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.calls).toEqual(["current:1", "last"]);
  });

  it("asks only for a recent last-known fix in the background", async () => {
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.lastOptions).toEqual({ maxAge: LAST_KNOWN_FIX_MAX_AGE_MS });
  });

  it("reports the zone alone when the permission read itself fails", async () => {
    location.permissionThrows = true;
    try {
      await expect(
        readDeviceContext({ shareLocation: true, mode: "foreground" }),
      ).resolves.toEqual({ timezone: "Asia/Tokyo" });
    } finally {
      location.permissionThrows = false;
    }
  });

  it("takes a fresh fix in the foreground and the last known one in the background", async () => {
    await expect(
      readDeviceContext({ shareLocation: true, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Asia/Tokyo",
      position: {
        latitude: 35.6762,
        longitude: 139.6503,
        accuracyM: 50,
        place: { city: "Tokyo", region: null, country: "Japan" },
      },
    });
    expect(location.calls).toEqual(["current:3"]);
    location.calls = [];
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.calls).toEqual(["last"]);
  });

  it("reports the zone alone when location is not granted or no fix exists", async () => {
    location.granted = false;
    await expect(
      readDeviceContext({ shareLocation: true, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Asia/Tokyo",
    });
    location.granted = true;
    location.last = null;
    await expect(
      readDeviceContext({ shareLocation: true, mode: "background" }),
    ).resolves.toEqual({
      timezone: "Asia/Tokyo",
    });
  });
});
