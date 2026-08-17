import { describe, expect, it } from "vitest";
import type { DeviceInfo } from "@vesta/core";
import { contextLine } from "./context-line";

function device(overrides: Partial<DeviceInfo>): DeviceInfo {
  return {
    id: "dev-1",
    kind: "mobile",
    descriptor: "Vesta Mobile on iOS",
    present: true,
    lastSeen: "2026-01-01T00:00:00Z",
    pushEnabled: true,
    location: null,
    timezone: null,
    position: null,
    positionAt: null,
    ...overrides,
  };
}

describe("contextLine", () => {
  it("prefers the reported place, then the zone", () => {
    expect(
      contextLine(
        device({
          location: "London, United Kingdom",
          timezone: "Asia/Tokyo",
          position: {
            latitude: 35.6,
            longitude: 139.6,
            accuracyM: null,
            place: { city: "Tokyo", region: null, country: "Japan" },
          },
        }),
      ),
    ).toBe("Tokyo, Japan · Asia/Tokyo");
  });

  it("falls back to the gateway's IP location and hides an empty line", () => {
    expect(contextLine(device({ location: "London, United Kingdom" }))).toBe(
      "London, United Kingdom",
    );
    expect(contextLine(device({}))).toBeNull();
  });
});
