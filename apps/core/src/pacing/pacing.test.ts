import { describe, expect, it } from "vitest"

import { PACING, typingDelay } from "./pacing"

describe("typingDelay", () => {
  it("keeps the same constants web shipped", () => {
    expect(PACING).toEqual({
      perChar: 25,
      min: 1500,
      max: 6000,
      variance: 0.2,
      flushThreshold: 3,
      maxMessages: 5000,
    })
  })

  it("floors at min for short text and caps at max plus variance for long text", () => {
    // rng=0.5 => zero net jitter (floor(raw*variance) * (2*0.5) - variance == 0 only when raw*variance even;
    // assert the pre-jitter envelope instead by pinning rng to its extremes).
    expect(typingDelay(0, () => 0)).toBe(1500 - Math.floor(1500 * 0.2))
    expect(typingDelay(1000, () => 0)).toBe(6000 - Math.floor(6000 * 0.2))
  })

  it("adds bounded positive jitter at rng=1", () => {
    const variance = Math.floor(1500 * 0.2)
    expect(typingDelay(0, () => 0.999999)).toBe(1500 + variance - 1)
  })

  it("is monotonic in char count before the cap", () => {
    const mid = () => 0.5
    expect(typingDelay(10, mid)).toBeLessThanOrEqual(typingDelay(200, mid))
  })
})
