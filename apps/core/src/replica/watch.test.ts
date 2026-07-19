import { describe, expect, it } from "vitest"

import { createWatchManager } from "./watch"

describe("createWatchManager", () => {
  it("tracks desired agents in insertion order", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    manager.watch("atlas")
    expect(manager.desired()).toEqual(["scout", "atlas"])
  })

  it("deduplicates repeated watches", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    manager.watch("scout")
    expect(manager.desired()).toEqual(["scout"])
  })

  it("drops an agent on unwatch", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    manager.watch("atlas")
    manager.unwatch("scout")
    expect(manager.desired()).toEqual(["atlas"])
  })

  it("returns a fresh array each call", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    const first = manager.desired()
    first.push("mutated")
    expect(manager.desired()).toEqual(["scout"])
  })

  it("signals the wire transition: watch true only on 0->1, unwatch true only on 1->0", () => {
    const manager = createWatchManager()
    expect(manager.watch("scout")).toBe(true)
    expect(manager.watch("scout")).toBe(false)
    expect(manager.unwatch("scout")).toBe(false)
    expect(manager.unwatch("scout")).toBe(true)
  })

  it("keeps an agent watched while any reference remains, then drops on the last unwatch", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    manager.watch("scout")
    manager.unwatch("scout")
    expect(manager.desired()).toEqual(["scout"])
    manager.unwatch("scout")
    expect(manager.desired()).toEqual([])
  })

  it("is a no-op that returns false when unwatching an unreferenced agent", () => {
    const manager = createWatchManager()
    expect(manager.unwatch("scout")).toBe(false)
    expect(manager.desired()).toEqual([])
  })

  it("drops an agent regardless of its reference count", () => {
    const manager = createWatchManager()
    manager.watch("scout")
    manager.watch("scout")
    manager.drop("scout")
    expect(manager.desired()).toEqual([])
  })
})
