import { getCalendars } from "expo-localization";
import * as Location from "expo-location";
import tzlookup from "tz-lookup";
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
// iOS keeps this zone correct from the network and location, so it is the fallback when no fix is in
// hand, and it is never held above a fix, which is the more precise source.
function deviceTimezone(): string | undefined {
  return getCalendars()[0]?.timeZone ?? undefined;
}

// The IANA zone the fix falls in, from an embedded offline boundary table: deterministic, network
// free, and identical on both platforms, so the reported zone is the one the user stands in. `null`
// only for coordinates the table rejects, which a real fix is not.
function zoneAt(latitude: number, longitude: number): string | null {
  try {
    return tzlookup(latitude, longitude);
  } catch {
    return null;
  }
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

// The position plus the IANA zone the fix falls in, or undefined when the user has not granted
// location, no fix is available, or the read fails: a report then carries the device's own zone
// alone. The zone comes from the coordinates, not the network geocoder, so it is always present with
// a fix. Reverse geocoding is best-effort and only names the macro place.
interface LocatedContext {
  position: DevicePosition;
  zone: string | null;
}

async function readDevicePosition(
  mode: PositionMode,
): Promise<LocatedContext | undefined> {
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
  return {
    position: toDevicePosition(
      { latitude, longitude, accuracy },
      geocoded[0] ?? null,
    ),
    zone: zoneAt(latitude, longitude),
  };
}

// The zone the fix falls in wins over the device's own, which covers the rare case of an OS clock
// that lags the user's travel; with no fix the OS zone is the fallback, so the phone always names a
// zone. With sharing off the report carries `position: null`, which retracts the position the
// gateway holds for this device, and names the OS zone alone.
export async function readDeviceContext(input: {
  shareLocation: boolean;
  mode: PositionMode;
}): Promise<DeviceContext> {
  const context: DeviceContext = {};
  if (!input.shareLocation) {
    const timezone = deviceTimezone();
    if (timezone !== undefined) context.timezone = timezone;
    context.position = null;
    return context;
  }
  const located = await readDevicePosition(input.mode);
  const timezone = located?.zone ?? deviceTimezone();
  if (timezone !== undefined && timezone !== null) context.timezone = timezone;
  if (located !== undefined) context.position = located.position;
  return context;
}
