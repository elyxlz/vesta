import type { DeviceInfo } from "@vesta/core";

// The device's reported place and zone, falling back to the gateway's IP-derived location.
export function contextLine(device: DeviceInfo): string | null {
  const place = device.position?.place;
  const placeLabel =
    place && (place.city ?? place.region)
      ? [place.city ?? place.region, place.country].filter(Boolean).join(", ")
      : device.location;
  const parts = [placeLabel, device.timezone].filter(
    (part): part is string => typeof part === "string" && part.length > 0,
  );
  return parts.length > 0 ? parts.join(" · ") : null;
}
