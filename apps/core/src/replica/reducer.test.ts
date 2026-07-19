import { describe, expect, it } from "vitest"

import { reduceDelta } from "./reducer"
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
    agents: {
      scout: {
        info: {
          status: "alive",
          activityState: "idle",
          buildPhase: null,
          startedAt: null,
          services: {},
        },
        notifications: { pending: [] },
      },
    },
  }
}

describe("reduceDelta", () => {
  it("replaces the gateway branch on a state delta", () => {
    const next = reduceDelta(baseTree(), {
      type: "state",
      scope: "gateway",
      value: { ...baseTree().gateway, updateAvailable: true },
    })
    expect(next.gateway.updateAvailable).toBe(true)
  })

  it("upserts an agent and preserves its notifications", () => {
    const tree = baseTree()
    const seeded = tree.agents.scout
    if (seeded) {
      seeded.notifications.pending = [{ id: 1, type: "notification", source: "sms", summary: "hi" }]
    }
    const next = reduceDelta(tree, {
      type: "agent",
      name: "scout",
      info: {
        status: "restarting",
        activityState: "idle",
        buildPhase: null,
        startedAt: null,
        services: {},
      },
    })
    expect(next.agents.scout?.info.status).toBe("restarting")
    expect(next.agents.scout?.notifications.pending).toHaveLength(1)
  })

  it("adds a brand-new agent with an empty notification branch", () => {
    const next = reduceDelta(baseTree(), {
      type: "agent",
      name: "atlas",
      info: {
        status: "starting",
        activityState: "idle",
        buildPhase: "pulling",
        startedAt: null,
        services: {},
      },
    })
    expect(next.agents.atlas?.notifications.pending).toEqual([])
  })

  it("removes an agent", () => {
    const next = reduceDelta(baseTree(), { type: "agent_removed", name: "scout" })
    expect(next.agents.scout).toBeUndefined()
  })

  it("replaces the notification branch wholesale", () => {
    const next = reduceDelta(baseTree(), {
      type: "notifications",
      agent: "scout",
      pending: [{ id: 1, type: "notification", source: "sms", summary: "hi" }],
    })
    expect(next.agents.scout?.notifications.pending).toHaveLength(1)
  })

  it("returns the same tree for append and resync deltas", () => {
    const tree = baseTree()
    expect(reduceDelta(tree, { type: "append", agent: "scout", events: [] })).toBe(tree)
    expect(reduceDelta(tree, { type: "resync", agent: "scout" })).toBe(tree)
  })

  it("returns the same tree when removing an absent agent", () => {
    const tree = baseTree()
    expect(reduceDelta(tree, { type: "agent_removed", name: "ghost" })).toBe(tree)
  })

  it("does not mutate the input tree", () => {
    const tree = baseTree()
    reduceDelta(tree, { type: "agent_removed", name: "scout" })
    expect(tree.agents.scout).toBeDefined()
  })
})
