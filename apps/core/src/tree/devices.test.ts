import { describe, expect, it } from "vitest";
import type { DeviceInfo, Tree } from "../protocol/tree";
import { devicesEqual, selectDevices, splitSelfDevice } from "./devices";

function device(overrides: Partial<DeviceInfo> = {}): DeviceInfo {
  return {
    id: "dev-1",
    kind: "desktop",
    descriptor: "Vesta Desktop on macOS",
    present: true,
    lastSeen: "2026-01-01T00:00:00Z",
    pushEnabled: false,
    timezone: null,
    position: null,
    positionAt: null,
    ...overrides,
  };
}

describe("selectDevices", () => {
  it("returns the tree's devices", () => {
    const tree = {
      gateway: {},
      agents: {},
      devices: [device()],
    } as unknown as Tree;
    expect(selectDevices(tree)).toHaveLength(1);
  });

  it("returns an empty list for a null tree", () => {
    expect(selectDevices(null)).toEqual([]);
  });
});

describe("splitSelfDevice", () => {
  it("pins this device apart and orders the others present first, then most recent", () => {
    const devices = [
      device({ id: "old", present: false, lastSeen: "2026-01-01T00:00:00Z" }),
      device({ id: "me", present: true }),
      device({
        id: "recent",
        present: false,
        lastSeen: "2026-01-02T00:00:00Z",
      }),
      device({ id: "here", present: true, lastSeen: "2025-12-01T00:00:00Z" }),
    ];
    const split = splitSelfDevice(devices, "me");
    expect(split.self?.id).toBe("me");
    expect(split.others.map((d) => d.id)).toEqual(["here", "recent", "old"]);
  });

  it("has no self until the gateway registers this device", () => {
    const split = splitSelfDevice([device({ id: "other" })], "me");
    expect(split.self).toBeNull();
    expect(split.others.map((d) => d.id)).toEqual(["other"]);
    expect(splitSelfDevice([device()], null).self).toBeNull();
  });
});

describe("devicesEqual", () => {
  it("is true for structurally identical lists", () => {
    expect(devicesEqual([device()], [device()])).toBe(true);
  });

  it("is false when a field differs", () => {
    expect(
      devicesEqual([device({ present: true })], [device({ present: false })]),
    ).toBe(false);
  });

  it("is false when the reported context differs", () => {
    const tokyo = {
      latitude: 35.6762,
      longitude: 139.6503,
      accuracyM: 50,
      place: null,
    };
    expect(
      devicesEqual(
        [device({ timezone: "Asia/Tokyo" })],
        [device({ timezone: "Europe/London" })],
      ),
    ).toBe(false);
    expect(
      devicesEqual([device({ position: tokyo })], [device({ position: null })]),
    ).toBe(false);
    expect(
      devicesEqual(
        [device({ position: tokyo })],
        [
          device({
            position: {
              ...tokyo,
              place: { city: "Tokyo", region: null, country: "Japan" },
            },
          }),
        ],
      ),
    ).toBe(false);
    expect(
      devicesEqual(
        [device({ position: tokyo })],
        [device({ position: { ...tokyo } })],
      ),
    ).toBe(true);
  });

  it("is false when lengths differ", () => {
    expect(devicesEqual([device()], [])).toBe(false);
  });
});
