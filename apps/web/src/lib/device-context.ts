import tzlookup from "tz-lookup";
import type { DeviceContext } from "@vesta/core";

// What this browser (or the desktop app around it) reports about itself: its zone always, and, with
// the user's opt-in and a geolocation grant, its position and the zone that position falls in. A
// laptop has no cellular network to mislead its OS clock, so the OS zone is a sound fallback here,
// unlike on a roaming phone.

// A fix that takes longer than this (denied prompt left open, no provider) is given up on, so the
// zone report is never held back by the position.
export const FRESH_FIX_TIMEOUT_MS = 15_000;

// The OS zone, read live: the browser asks the platform, so a zone change lands on the next report.
function osTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

// The IANA zone the fix falls in, from an embedded offline boundary table. Falls back to the OS zone
// only for coordinates the table rejects, which a real fix is not.
function zoneAt(latitude: number, longitude: number): string {
  try {
    return tzlookup(latitude, longitude);
  } catch {
    return osTimezone();
  }
}

// A fix, or null when geolocation is unavailable, denied, or slow: the report then carries the OS
// zone alone. The browser prompt is raised by this call itself, so the opt-in toggle is what gates it.
function readFix(): Promise<GeolocationPosition | null> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return Promise.resolve(null);
  }
  const { geolocation } = navigator;
  return new Promise((resolve) => {
    geolocation.getCurrentPosition(
      (fix) => {
        resolve(fix);
      },
      () => {
        resolve(null);
      },
      { timeout: FRESH_FIX_TIMEOUT_MS },
    );
  });
}

// With sharing off the report carries `position: null`, which retracts any position the gateway
// holds for this device; with sharing on but no fix, the position is absent and the stored one
// stands. The browser has no offline reverse geocoder, so the position names no place; the gateway's
// coarse IP city is the only place hint for a browser or desktop device.
export async function readBrowserDeviceContext(
  shareLocation: boolean,
): Promise<DeviceContext> {
  if (!shareLocation) {
    return { timezone: osTimezone(), position: null };
  }
  const fix = await readFix();
  if (fix === null) return { timezone: osTimezone() };
  const { latitude, longitude, accuracy } = fix.coords;
  return {
    timezone: zoneAt(latitude, longitude),
    position: { latitude, longitude, accuracyM: accuracy, place: null },
  };
}
