import { afterEach, describe, expect, it, vi } from "vitest";
import { readBrowserDeviceContext } from "./device-context";

type SuccessFn = (fix: {
  coords: { latitude: number; longitude: number; accuracy: number };
}) => void;
type ErrorFn = (error: unknown) => void;

function stubOsZone(zone: string): void {
  vi.stubGlobal("Intl", {
    DateTimeFormat: () => ({ resolvedOptions: () => ({ timeZone: zone }) }),
  });
}

function stubGeolocation(
  impl: (success: SuccessFn, error: ErrorFn) => void,
): void {
  vi.stubGlobal("navigator", { geolocation: { getCurrentPosition: impl } });
}

describe("readBrowserDeviceContext", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reports the OS zone and retracts the position when sharing is off", async () => {
    stubOsZone("America/New_York");
    const getCurrentPosition = vi.fn();
    stubGeolocation(getCurrentPosition);
    await expect(readBrowserDeviceContext(false)).resolves.toEqual({
      timezone: "America/New_York",
      position: null,
    });
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("reports the zone the fix falls in and the position when sharing is on", async () => {
    stubOsZone("America/New_York");
    stubGeolocation((success) => {
      success({
        coords: { latitude: 39.2238, longitude: 9.1217, accuracy: 20 },
      });
    });
    await expect(readBrowserDeviceContext(true)).resolves.toEqual({
      timezone: "Europe/Rome",
      position: {
        latitude: 39.2238,
        longitude: 9.1217,
        accuracyM: 20,
        place: null,
      },
    });
  });

  it("falls back to the OS zone when geolocation is denied", async () => {
    stubOsZone("America/New_York");
    stubGeolocation((_success, error) => {
      error(new Error("denied"));
    });
    await expect(readBrowserDeviceContext(true)).resolves.toEqual({
      timezone: "America/New_York",
    });
  });

  it("falls back to the OS zone when geolocation is unavailable", async () => {
    stubOsZone("America/New_York");
    vi.stubGlobal("navigator", {});
    await expect(readBrowserDeviceContext(true)).resolves.toEqual({
      timezone: "America/New_York",
    });
  });
});
