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
})
