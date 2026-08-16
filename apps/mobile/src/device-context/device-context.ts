import { getCalendars } from "expo-localization";
import * as Location from "expo-location";
import type { DeviceContext, DevicePlace, DevicePosition } from "@vesta/core";

// What the phone reports about itself: its zone (always) and, with the user's opt-in, its position
// plus the macro place the OS geocoder gives for it. One reader for the foreground reporter and the
// background poll; `mode` picks a fresh fix (foreground) or the OS's last known one (background,
// which needs no "Always" permission).
export type PositionMode = "foreground" | "background";

// A fix as expo-location hands it over, narrowed to what the wire carries.
export interface Fix {
  latitude: number;
  longitude: number;
  accuracy: number | null;
}

// A reverse-geocode row as expo-location hands it over, narrowed to the macro parts.
export interface Geocoded {
  city: string | null;
  region: string | null;
  country: string | null;
}

// Read live on every call: expo-localization asks the OS, so a zone change lands on the next report.
export function deviceTimezone(): string | undefined {
  return getCalendars()[0].timeZone ?? undefined;
}

export function toDevicePosition(
  fix: Fix,
  geocoded: Geocoded | null,
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

// The position, or undefined when the user has not granted location, no fix is available, or the
// read fails: a report then carries the zone alone. Reverse geocoding is best-effort.
export async function readDevicePosition(
  mode: PositionMode,
): Promise<DevicePosition | undefined> {
  const permission = await Location.getForegroundPermissionsAsync();
  if (!permission.granted) return undefined;
  const fix =
    mode === "foreground"
      ? await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        }).catch(() => null)
      : await Location.getLastKnownPositionAsync().catch(() => null);
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

export async function readDeviceContext(input: {
  shareLocation: boolean;
  mode: PositionMode;
}): Promise<DeviceContext> {
  const context: DeviceContext = {};
  const timezone = deviceTimezone();
  if (timezone !== undefined) context.timezone = timezone;
  if (input.shareLocation) {
    const position = await readDevicePosition(input.mode);
    if (position !== undefined) context.position = position;
  }
  return context;
}
