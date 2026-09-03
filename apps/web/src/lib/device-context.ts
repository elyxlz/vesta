import tzlookup from "tz-lookup";
import type { DeviceContext } from "@vesta/core";
import { native } from "@/lib/native";

// What this browser (or the desktop app around it) reports about itself: its zone always, and, with
// the user's opt-in and a geolocation grant, its position and the zone that position falls in. A
// laptop has no cellular network to mislead its OS clock, so the OS zone is a sound fallback here,
// unlike on a roaming phone.

// A fix that takes longer than this (denied prompt left open, no provider) is given up on, so the
// zone report is never held back by the position.
const FRESH_FIX_TIMEOUT_MS = 15_000;

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

interface Fix {
  latitude: number;
  longitude: number;
  accuracy: number | null;
}

function browserFix(): Promise<Fix | null> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return Promise.resolve(null);
  }
  const { geolocation } = navigator;
  return new Promise((resolve) => {
    geolocation.getCurrentPosition(
      (fix) => {
        const { latitude, longitude, accuracy } = fix.coords;
        resolve({ latitude, longitude, accuracy });
      },
      () => {
        resolve(null);
      },
      { timeout: FRESH_FIX_TIMEOUT_MS },
    );
  });
}

// A fix, or null when geolocation is unavailable, denied, or slow: the report then carries the OS
// zone alone. The desktop app resolves through the OS provider in its main process on every
// platform, and that answer is final: the renderer's own geolocation is never a fallback there,
// since in Electron it hangs on macOS and needs a Google API key elsewhere. Only a plain browser
// asks navigator.geolocation, whose prompt this call itself raises, so the opt-in toggle gates it.
async function readFix(): Promise<Fix | null> {
  if (native.readGeolocation) {
    const fix = await native.readGeolocation().catch(() => null);
    if (fix === null) return null;
    return {
      latitude: fix.latitude,
      longitude: fix.longitude,
      accuracy: fix.accuracyM,
    };
  }
  return browserFix();
}

// With sharing off the report carries `position: null`, which retracts any position the gateway
// holds for this device; with sharing on but no fix, the position is absent and the stored one
// stands. The browser has no offline reverse geocoder, so the position names no place.
export async function readBrowserDeviceContext(
  shareLocation: boolean,
): Promise<DeviceContext> {
  if (!shareLocation) {
    return { timezone: osTimezone(), position: null };
  }
  const fix = await readFix();
  if (fix === null) return { timezone: osTimezone() };
  const { latitude, longitude, accuracy } = fix;
  return {
    timezone: zoneAt(latitude, longitude),
    position: { latitude, longitude, accuracyM: accuracy, place: null },
  };
}
