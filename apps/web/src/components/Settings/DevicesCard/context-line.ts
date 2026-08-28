import type { DeviceInfo } from "@vesta/core";

// The device's reported place (from its GPS position) and zone. `locationFallback`
// fills the place slot when the device reports no location (e.g. this device with
// sharing off), so the row shows a message instead of dropping it.
export function contextLine(
  device: DeviceInfo,
  locationFallback?: string,
): string | null {
  const place = device.position?.place;
  const placeLabel =
    place && (place.city ?? place.region)
      ? [place.city ?? place.region, place.country].filter(Boolean).join(", ")
      : null;
  const parts = [
    placeLabel ?? locationFallback ?? null,
    device.timezone,
  ].filter(
    (part): part is string => typeof part === "string" && part.length > 0,
  );
  return parts.length > 0 ? parts.join(" · ") : null;
}
