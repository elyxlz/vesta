import { describe, expect, it } from "vitest"

import fixtures from "../../fixtures/sync-protocol.json"
import { parseServerFrame } from "./parse"

// The fixtures are produced by vestad's real serde path (vestad/src/sync/protocol.rs,
// REGEN_API_FIXTURES=1). Parsing every one with the canonical types proves the Rust->TS seam.
describe("sync protocol contract (vestad fixtures)", () => {
  it("parses the hello frame vestad emits, carrying the served version window", () => {
    const parsed = parseServerFrame(JSON.stringify(fixtures.hello))
    expect(parsed.kind).toBe("hello")
    if (parsed.kind === "hello") {
      expect(typeof parsed.frame.version).toBe("string")
      expect(parsed.frame.minSupported).toBe("0.0.0")
    }
  })

  it("parses the snapshot frame and preserves the tree", () => {
    const parsed = parseServerFrame(JSON.stringify(fixtures.snapshot))
    expect(parsed.kind).toBe("snapshot")
    if (parsed.kind === "snapshot") {
      expect(parsed.frame.tree.gateway.autoUpdate).toBe(true)
      expect(parsed.frame.tree.agents["sample-agent"]?.info.activityState).toBe("thinking")
    }
  })

  it("classifies every delta vestad emits", () => {
    for (const [type, frame] of Object.entries(fixtures.deltas)) {
      const parsed = parseServerFrame(JSON.stringify(frame))
      expect(parsed.kind).toBe("delta")
      if (parsed.kind === "delta") expect(parsed.delta.type).toBe(type)
    }
  })

  it("carries the server-decided kind, title, and body through the user_notification delta", () => {
    const parsed = parseServerFrame(JSON.stringify(fixtures.deltas.user_notification))
    expect(parsed.kind).toBe("delta")
    if (parsed.kind === "delta" && parsed.delta.type === "user_notification") {
      expect(parsed.delta.agent).toBe("sample-agent")
      expect(parsed.delta.kind).toBe("message")
      expect(parsed.delta.title).toBe("sample-agent")
      expect(parsed.delta.body).toBe("hello")
    }
  })
})
