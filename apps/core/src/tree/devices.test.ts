import { describe, expect, it } from "vitest"
import type { DeviceInfo, Tree } from "../protocol/tree"
import { devicesEqual, selectDevices } from "./devices"

function device(overrides: Partial<DeviceInfo> = {}): DeviceInfo {
  return {
    id: "dev-1",
    kind: "desktop",
    descriptor: "Vesta Desktop on macOS",
    present: true,
    lastSeen: "2026-01-01T00:00:00Z",
    pushEnabled: false,
    location: null,
    timezone: null,
    position: null,
    positionAt: null,
    ...overrides,
  }
}

describe("selectDevices", () => {
  it("returns the tree's devices", () => {
    const tree = { gateway: {}, agents: {}, devices: [device()] } as unknown as Tree
    expect(selectDevices(tree)).toHaveLength(1)
  })

  it("returns an empty list for a null tree", () => {
    expect(selectDevices(null)).toEqual([])
  })
})

describe("devicesEqual", () => {
  it("is true for structurally identical lists", () => {
    expect(devicesEqual([device()], [device()])).toBe(true)
  })

  it("is false when a field differs", () => {
    expect(devicesEqual([device({ present: true })], [device({ present: false })])).toBe(false)
  })

  it("is false when the reported context differs", () => {
    const tokyo = { latitude: 35.6762, longitude: 139.6503, accuracyM: 50, place: null }
    expect(
      devicesEqual([device({ timezone: "Asia/Tokyo" })], [device({ timezone: "Europe/London" })]),
    ).toBe(false)
    expect(devicesEqual([device({ position: tokyo })], [device({ position: null })])).toBe(false)
    expect(
      devicesEqual(
        [device({ position: tokyo })],
        [
          device({
            position: { ...tokyo, place: { city: "Tokyo", region: null, country: "Japan" } },
          }),
        ],
      ),
    ).toBe(false)
    expect(devicesEqual([device({ position: tokyo })], [device({ position: { ...tokyo } })])).toBe(
      true,
    )
  })

  it("is false when lengths differ", () => {
    expect(devicesEqual([device()], [])).toBe(false)
  })
})
