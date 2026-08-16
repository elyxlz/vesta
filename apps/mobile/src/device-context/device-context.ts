import { getCalendars } from "expo-localization";
import * as Location from "expo-location";
import type { DeviceContext, DevicePlace, DevicePosition } from "@vesta/core";

// What the phone reports about itself: its zone (always) and, with the user's opt-in, its position
// plus the macro place the OS geocoder gives for it. One reader for the foreground reporter and the
// background poll; `mode` picks a balanced fresh fix (foreground) or, in the background, a low-power
// fresh fix when the always-on grant allows one and the OS's last known fix otherwise.
export type PositionMode = "foreground" | "background";

// A fresh fix that takes longer than this (indoors, no satellites) is given up on, so the zone
// report is never held back by the position.
export const FRESH_FIX_TIMEOUT_MS = 15_000;
// A last-known fix older than this is not reported: stamped as fresh by the gateway, a stale one
// would place the user where they were, not where they are.
export const LAST_KNOWN_FIX_MAX_AGE_MS = 60 * 60 * 1000;

// A fix as expo-location hands it over, narrowed to what the wire carries.
interface Fix {
  latitude: number;
  longitude: number;
  accuracy: number | null;
}

// Read live on every call: expo-localization asks the OS, so a zone change lands on the next report.
function deviceTimezone(): string | undefined {
  return getCalendars()[0]?.timeZone ?? undefined;
}

// `geocoded` is the reverse-geocode row as expo-location hands it over, narrowed to the macro parts.
export function toDevicePosition(
  fix: Fix,
  geocoded: DevicePlace | null,
): DevicePosition {
  const place: DevicePlace | null =
    geocoded && (geocoded.city ?? geocoded.region ?? geocoded.country) !== null
      ? {
          city: geocoded.city,
          region: geocoded.region,
          country: geocoded.country,
        }
      : null;
  return {
    latitude: fix.latitude,
    longitude: fix.longitude,
    accuracyM: fix.accuracy,
    place,
  };
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expiry = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  return Promise.race([promise, expiry]).finally(() => clearTimeout(timer));
}

async function freshFix(
  accuracy: Location.LocationAccuracy,
): Promise<Location.LocationObject | null> {
  return withTimeout(
    Location.getCurrentPositionAsync({ accuracy }),
    FRESH_FIX_TIMEOUT_MS,
  ).catch(() => null);
}

async function readFix(
  mode: PositionMode,
): Promise<Location.LocationObject | null> {
  if (mode === "foreground") return freshFix(Location.Accuracy.Balanced);
  const background = await Location.getBackgroundPermissionsAsync().catch(
    () => null,
  );
  if (background?.granted) {
    const fix = await freshFix(Location.Accuracy.Low);
    if (fix) return fix;
  }
  return Location.getLastKnownPositionAsync({
    maxAge: LAST_KNOWN_FIX_MAX_AGE_MS,
  }).catch(() => null);
}

// The position, or undefined when the user has not granted location, no fix is available, or the
// read fails: a report then carries the zone alone. Reverse geocoding is best-effort.
async function readDevicePosition(
  mode: PositionMode,
): Promise<DevicePosition | undefined> {
  const permission = await Location.getForegroundPermissionsAsync().catch(
    () => null,
  );
  if (!permission?.granted) return undefined;
  const fix = await readFix(mode);
  if (!fix) return undefined;
  const { latitude, longitude, accuracy } = fix.coords;
  const geocoded = await Location.reverseGeocodeAsync({
    latitude,
    longitude,
  }).catch(() => []);
  return toDevicePosition(
    { latitude, longitude, accuracy },
    geocoded[0] ?? null,
  );
}

// With sharing off the report carries `position: null`, which retracts the position the gateway
// holds for this device; with sharing on but no fix, the field is absent and the stored one stands.
export async function readDeviceContext(input: {
  shareLocation: boolean;
  mode: PositionMode;
}): Promise<DeviceContext> {
  const context: DeviceContext = {};
  const timezone = deviceTimezone();
  if (timezone !== undefined) context.timezone = timezone;
  if (!input.shareLocation) {
    context.position = null;
    return context;
  }
  const position = await readDevicePosition(input.mode);
  if (position !== undefined) context.position = position;
  return context;
}
