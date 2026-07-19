import { describe, expect, it } from "vitest"

import { parseServerFrame } from "./parse"

describe("parseServerFrame", () => {
  it("parses a hello frame", () => {
    const parsed = parseServerFrame(
      JSON.stringify({ type: "hello", version: "0.2.0", protocol: 1, floor: 1 }),
    )
    expect(parsed).toEqual({
      kind: "hello",
      frame: { type: "hello", version: "0.2.0", protocol: 1, floor: 1 },
    })
  })

  it("parses a snapshot frame and preserves the tree", () => {
    const tree = { gateway: {}, agents: {} }
    const parsed = parseServerFrame(JSON.stringify({ type: "snapshot", tree }))
    expect(parsed.kind).toBe("snapshot")
    if (parsed.kind === "snapshot") expect(parsed.frame.tree).toEqual(tree)
  })

  it("classifies each delta type", () => {
    const cases: { raw: Record<string, unknown>; type: string }[] = [
      { raw: { type: "state", scope: "gateway", value: { version: "1" } }, type: "state" },
      { raw: { type: "agent", name: "scout", info: { status: "alive" } }, type: "agent" },
      { raw: { type: "agent_removed", name: "scout" }, type: "agent_removed" },
      { raw: { type: "append", agent: "scout", events: [] }, type: "append" },
      { raw: { type: "notifications", agent: "scout", pending: [] }, type: "notifications" },
      { raw: { type: "resync", agent: "scout" }, type: "resync" },
      {
        raw: { type: "alert", agent: "scout", event: { id: 1, type: "chat", text: "hi" }, preview: "hi" },
        type: "alert",
      },
    ]
    for (const entry of cases) {
      const parsed = parseServerFrame(JSON.stringify(entry.raw))
      expect(parsed.kind).toBe("delta")
      if (parsed.kind === "delta") expect(parsed.delta.type).toBe(entry.type)
    }
  })

  it("carries the alert agent, event, and preview through", () => {
    const parsed = parseServerFrame(
      JSON.stringify({
        type: "alert",
        agent: "scout",
        event: { id: 9, type: "chat", text: "hello there" },
        preview: "hello there",
      }),
    )
    expect(parsed.kind).toBe("delta")
    if (parsed.kind === "delta" && parsed.delta.type === "alert") {
      expect(parsed.delta.agent).toBe("scout")
      expect(parsed.delta.preview).toBe("hello there")
      expect(parsed.delta.event.id).toBe(9)
    }
  })

  it("ignores an alert missing its preview or event", () => {
    const inputs = [
      JSON.stringify({ type: "alert", agent: "scout", event: { id: 1, type: "chat", text: "hi" } }),
      JSON.stringify({ type: "alert", agent: "scout", preview: "hi" }),
    ]
    for (const raw of inputs) expect(parseServerFrame(raw)).toEqual({ kind: "unknown" })
  })

  it("ignores unknown frame and delta types", () => {
    const inputs = [
      JSON.stringify({ type: "future_frame", data: 1 }),
      JSON.stringify({ type: "future_delta", agent: "scout" }),
    ]
    for (const raw of inputs) expect(parseServerFrame(raw)).toEqual({ kind: "unknown" })
  })

  it("ignores malformed input", () => {
    const inputs = ["not json", "null", "123", JSON.stringify({ noType: true })]
    for (const raw of inputs) expect(parseServerFrame(raw)).toEqual({ kind: "unknown" })
  })

  it("ignores a delta missing a required field", () => {
    const inputs = [
      JSON.stringify({ type: "agent", name: "scout" }),
      JSON.stringify({ type: "append", agent: "scout" }),
      JSON.stringify({ type: "state", scope: "other", value: {} }),
    ]
    for (const raw of inputs) expect(parseServerFrame(raw)).toEqual({ kind: "unknown" })
  })
})
