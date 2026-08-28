import tzlookup from "tz-lookup";
import type { DeviceContext } from "@vesta/core";
import { native } from "@/lib/native";

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
// zone alone. In the desktop app the main process resolves through the OS provider first (WinRT on
// Windows, GeoClue2 on Linux); a null answer (macOS, no provider, refused) falls through to the
// renderer's own geolocation, whose prompt this call itself raises, so the opt-in toggle gates both.
async function readFix(): Promise<Fix | null> {
  if (native.readGeolocation) {
    const fix = await native.readGeolocation().catch(() => null);
    if (fix) {
      return {
        latitude: fix.latitude,
        longitude: fix.longitude,
        accuracy: fix.accuracyM,
      };
    }
  }
  return browserFix();
}

// TEMPORARY diagnostic (remove after debugging desktop location): on enable, report exactly why a
// fix is null on this platform, both the native-provider outcome and the navigator.geolocation
// error, so the failure the renderer actually sees can be pasted back.
export interface GeoProbe {
  ok: boolean;
  detail: string;
}

function geoErrorName(code: number): string {
  if (code === 1) return "PERMISSION_DENIED";
  if (code === 2) return "POSITION_UNAVAILABLE";
  if (code === 3) return "TIMEOUT";
  return "UNKNOWN";
}

// Electron's macOS getCurrentPosition can hang with no callback and ignore its own timeout option,
// so each step gets a hard cap and "hung" is itself a reported outcome.
const PROBE_STEP_MS = 10_000;

function probeTimeout<T>(value: T): Promise<T> {
  return new Promise((resolve) =>
    setTimeout(() => resolve(value), PROBE_STEP_MS),
  );
}

function browserFixDetailed(): Promise<{
  fix: Fix | null;
  error: string | null;
}> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return Promise.resolve({
      fix: null,
      error: "navigator.geolocation unavailable",
    });
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      resolve({
        fix: null,
        error: "no callback within 10s (getCurrentPosition hung)",
      });
    }, PROBE_STEP_MS);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        clearTimeout(timer);
        const { latitude, longitude, accuracy } = position.coords;
        resolve({ fix: { latitude, longitude, accuracy }, error: null });
      },
      (error) => {
        clearTimeout(timer);
        resolve({
          fix: null,
          error: `code ${String(error.code)} ${geoErrorName(error.code)}: ${error.message}`,
        });
      },
      { timeout: PROBE_STEP_MS },
    );
  });
}

export async function probeGeolocation(): Promise<GeoProbe> {
  const lines: string[] = [
    `runtime=${native.runtime} platform=${native.platform}`,
  ];
  if (native.readGeolocation) {
    const outcome = await Promise.race([
      native.readGeolocation().then(
        (fix) => ({ kind: "fix" as const, fix }),
        (error: unknown) => ({ kind: "throw" as const, error }),
      ),
      probeTimeout({ kind: "timeout" as const }),
    ]);
    if (outcome.kind === "fix") {
      if (outcome.fix) return { ok: true, detail: "" };
      lines.push("native provider: returned null");
    } else if (outcome.kind === "throw") {
      // Electron prefixes a main-process throw with the IPC channel; keep only the provider's reason.
      const raw =
        outcome.error instanceof Error
          ? outcome.error.message
          : String(outcome.error);
      const reason = raw.replace(/^Error invoking remote method '[^']*': /, "");
      lines.push(`native provider: threw ${reason}`);
    } else {
      lines.push("native provider: no response within 10s");
    }
  } else {
    lines.push("native provider: not available (browser runtime)");
  }
  const browser = await browserFixDetailed();
  if (browser.fix) return { ok: true, detail: "" };
  lines.push(`navigator.geolocation: ${browser.error ?? "no fix"}`);
  return { ok: false, detail: lines.join("\n") };
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
