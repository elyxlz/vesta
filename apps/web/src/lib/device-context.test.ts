import { afterEach, describe, expect, it, vi } from "vitest";
import type { NativeGeolocationFix } from "@/lib/native";
import { readBrowserDeviceContext } from "./device-context";

// The native bridge as device-context sees it: no desktop main process here, so the default is
// the browser's null bridge; a test hands it a fix to play the desktop app.
const bridge = vi.hoisted(() => ({
  readGeolocation: null as (() => Promise<NativeGeolocationFix | null>) | null,
}));
vi.mock("@/lib/native", () => ({ native: bridge }));

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
  afterEach(() => {
    bridge.readGeolocation = null;
    vi.unstubAllGlobals();
  });

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

  it("prefers the desktop bridge fix over the renderer's geolocation", async () => {
    stubOsZone("America/New_York");
    const getCurrentPosition = vi.fn();
    stubGeolocation(getCurrentPosition);
    bridge.readGeolocation = () =>
      Promise.resolve({ latitude: 39.2238, longitude: 9.1217, accuracyM: 30 });
    await expect(readBrowserDeviceContext(true)).resolves.toEqual({
      timezone: "Europe/Rome",
      position: {
        latitude: 39.2238,
        longitude: 9.1217,
        accuracyM: 30,
        place: null,
      },
    });
    expect(getCurrentPosition).not.toHaveBeenCalled();
  });

  it("falls through to the renderer's geolocation when the bridge answers null", async () => {
    stubOsZone("America/New_York");
    stubGeolocation((success) => {
      success({
        coords: { latitude: 39.2238, longitude: 9.1217, accuracy: 20 },
      });
    });
    bridge.readGeolocation = () => Promise.resolve(null);
    await expect(readBrowserDeviceContext(true)).resolves.toMatchObject({
      timezone: "Europe/Rome",
    });
  });
});
