import { beforeEach, describe, expect, it, vi } from "vitest";
import { readDeviceContext, toDevicePosition } from "./device-context";

const location = vi.hoisted(() => ({
  granted: true,
  current: null as {
    coords: { latitude: number; longitude: number; accuracy: number | null };
  } | null,
  last: null as {
    coords: { latitude: number; longitude: number; accuracy: number | null };
  } | null,
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
    Promise.resolve({ granted: location.granted }),
  getCurrentPositionAsync: () => {
    location.calls.push("current");
    return Promise.resolve(location.current);
  },
  getLastKnownPositionAsync: () => {
    location.calls.push("last");
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
    location.current = tokyo;
    location.last = tokyo;
    location.geocoded = [{ city: "Tokyo", region: null, country: "Japan" }];
    location.calls = [];
  });

  it("reports the zone alone when location is not shared", async () => {
    await expect(
      readDeviceContext({ shareLocation: false, mode: "foreground" }),
    ).resolves.toEqual({
      timezone: "Asia/Tokyo",
    });
    expect(location.calls).toEqual([]);
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
    expect(location.calls).toEqual(["current"]);
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
