import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  BACKGROUND_FIX_TIMEOUT_MS,
  FRESH_FIX_TIMEOUT_MS,
  LAST_KNOWN_FIX_MAX_AGE_MS,
  readDeviceContext,
  toDevicePosition,
} from "./device-context";

const location = vi.hoisted(() => ({
  granted: true,
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
  Accuracy: { Balanced: 3 },
  getForegroundPermissionsAsync: () =>
    location.permissionThrows
      ? Promise.reject(new Error("no native module"))
      : Promise.resolve({ granted: location.granted }),
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

const sardinia = {
  coords: { latitude: 39.2238, longitude: 9.1217, accuracy: 20 },
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
    location.current = tokyo;
    location.last = tokyo;
    location.geocoded = [{ city: "Tokyo", region: null, country: "Japan" }];
    location.calls = [];
  });

  it("retracts the position and names the OS zone when location is not shared", async () => {
    await expect(
      readDeviceContext({ shareLocation: false, mode: "foreground" }),
    ).resolves.toEqual({ timezone: "Asia/Tokyo", position: null });
    expect(location.calls).toEqual([]);
  });

  it("falls back to the OS zone when a fresh fix never arrives", async () => {
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

  it("takes a balanced fresh fix in the background, with the last known one as the fallback", async () => {
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.calls).toEqual(["current:3"]);
    location.calls = [];
    location.current = null;
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.calls).toEqual(["current:3", "last"]);
  });

  it("waits for a background fresh fix only as long as a location wake-up lasts", async () => {
    vi.useFakeTimers();
    try {
      location.pending = true;
      const report = readDeviceContext({
        shareLocation: true,
        mode: "background",
      });
      await vi.advanceTimersByTimeAsync(BACKGROUND_FIX_TIMEOUT_MS);
      await expect(report).resolves.toMatchObject({
        position: { latitude: 35.6762, longitude: 139.6503 },
      });
      expect(location.calls).toEqual(["current:3", "last"]);
    } finally {
      location.pending = false;
      vi.useRealTimers();
    }
  });

  it("asks only for a recent last-known fix in the background", async () => {
    await readDeviceContext({ shareLocation: true, mode: "background" });
    expect(location.lastOptions).toEqual({ maxAge: LAST_KNOWN_FIX_MAX_AGE_MS });
  });

  it("falls back to the OS zone when the permission read itself fails", async () => {
    location.permissionThrows = true;
    try {
      await expect(
        readDeviceContext({ shareLocation: true, mode: "foreground" }),
      ).resolves.toEqual({ timezone: "Asia/Tokyo" });
    } finally {
      location.permissionThrows = false;
    }
  });

  it("reports the fresh fix with its place and zone", async () => {
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
  });

  it("reports the zone the fix falls in, not the device's own (roaming)", async () => {
    // The OS clock is pinned to Asia/Tokyo (a UK SIM would pin London), but the fix is in Sardinia.
    location.current = sardinia;
    location.geocoded = [
      { city: "Cagliari", region: "Sardinia", country: "Italy" },
    ];
    await expect(
      readDeviceContext({ shareLocation: true, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Europe/Rome",
      position: {
        latitude: 39.2238,
        longitude: 9.1217,
        accuracyM: 20,
        place: { city: "Cagliari", region: "Sardinia", country: "Italy" },
      },
    });
  });

  it("reports the zone the fix falls in even when the place cannot be geocoded (offline)", async () => {
    location.current = sardinia;
    location.geocoded = [];
    await expect(
      readDeviceContext({ shareLocation: true, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Europe/Rome",
      position: {
        latitude: 39.2238,
        longitude: 9.1217,
        accuracyM: 20,
        place: null,
      },
    });
  });

  it("falls back to the OS zone when location is not granted or no fix exists", async () => {
    location.granted = false;
    await expect(
      readDeviceContext({ shareLocation: true, mode: "foreground" }),
    ).resolves.toEqual({ timezone: "Asia/Tokyo" });
    location.granted = true;
    location.current = null;
    location.last = null;
    await expect(
      readDeviceContext({ shareLocation: true, mode: "background" }),
    ).resolves.toEqual({ timezone: "Asia/Tokyo" });
  });
});
