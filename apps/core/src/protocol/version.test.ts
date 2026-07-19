import { describe, expect, it } from "vitest"

import { PROTOCOL_FLOOR, PROTOCOL_VERSION } from "./version"

describe("protocol version", () => {
  it("is version 1 with floor 1", () => {
    expect(PROTOCOL_VERSION).toBe(1)
    expect(PROTOCOL_FLOOR).toBe(1)
  })

  it("floor never exceeds version", () => {
    expect(PROTOCOL_FLOOR).toBeLessThanOrEqual(PROTOCOL_VERSION)
  })
})
