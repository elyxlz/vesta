import { describe, expect, it, vi } from "vitest"

import { createReplica } from "./store"
import type { Tree } from "../protocol/tree"

function baseTree(): Tree {
  return {
    gateway: {
      version: "0.2.0",
      channel: "stable",
      autoUpdate: true,
      port: 4111,
      lan: { exposed: false, url: null },
      tunnelUrl: null,
      updateAvailable: false,
      latestVersion: null,
      managed: false,
    },
    agents: {},
  }
}

describe("createReplica", () => {
  it("starts empty and adopts the first snapshot", () => {
    const replica = createReplica()
    expect(replica.getState()).toBeNull()
    replica.applySnapshot(baseTree())
    expect(replica.getState()?.gateway.port).toBe(4111)
  })

  it("notifies subscribers on snapshot and delta", () => {
    const replica = createReplica()
    const listener = vi.fn()
    replica.subscribe(listener)
    replica.applySnapshot(baseTree())
    replica.applyDelta({
      type: "agent",
      name: "scout",
      info: {
        status: "alive",
        activityState: "idle",
        buildPhase: null,
        startedAt: null,
        services: {},
      },
    })
    expect(listener).toHaveBeenCalledTimes(2)
    expect(replica.getState()?.agents.scout?.info.status).toBe("alive")
  })

  it("ignores deltas that arrive before the first snapshot", () => {
    const replica = createReplica()
    const listener = vi.fn()
    replica.subscribe(listener)
    replica.applyDelta({ type: "agent_removed", name: "scout" })
    expect(listener).not.toHaveBeenCalled()
    expect(replica.getState()).toBeNull()
  })

  it("stops notifying after unsubscribe", () => {
    const replica = createReplica()
    const listener = vi.fn()
    const off = replica.subscribe(listener)
    off()
    replica.applySnapshot(baseTree())
    expect(listener).not.toHaveBeenCalled()
  })

  it("does not notify when a delta leaves the tree unchanged", () => {
    const replica = createReplica()
    replica.applySnapshot(baseTree())
    const listener = vi.fn()
    replica.subscribe(listener)
    replica.applyDelta({ type: "agent_removed", name: "ghost" })
    expect(listener).not.toHaveBeenCalled()
  })
})
