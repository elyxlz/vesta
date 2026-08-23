import { describe, expect, it } from "vitest"

import { voiceBoolSetting, voiceDomainReady, type VoiceDomainStatus } from "./status"

const status = (over: Partial<VoiceDomainStatus>): VoiceDomainStatus => ({
  configured: true,
  provider: "deepgram",
  enabled: true,
  ...over,
})

describe("voiceDomainReady", () => {
  it("is ready only when configured and enabled", () => {
    expect(voiceDomainReady(status({}))).toBe(true)
    expect(voiceDomainReady(status({ enabled: false }))).toBe(false)
    expect(voiceDomainReady(status({ configured: false }))).toBe(false)
    expect(voiceDomainReady(null)).toBe(false)
  })
})

describe("voiceBoolSetting", () => {
  it("reads a boolean setting by key", () => {
    const withSetting = status({
      settings: [{ key: "auto_send", type: "bool", label: "Auto send", value: false }],
    })
    expect(voiceBoolSetting(withSetting, "auto_send", true)).toBe(false)
  })

  it("falls back when the setting is missing or not a boolean", () => {
    expect(voiceBoolSetting(status({}), "auto_send", true)).toBe(true)
    const wrongType = status({
      settings: [{ key: "auto_send", type: "number", label: "Auto send", value: 3 }],
    })
    expect(voiceBoolSetting(wrongType, "auto_send", false)).toBe(false)
  })
})
