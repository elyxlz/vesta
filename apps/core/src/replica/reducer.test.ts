import { describe, expect, it } from "vitest"

import { reduceDelta } from "./reducer"
import type { Delta } from "../protocol/deltas"
import type { Tree } from "../protocol/tree"

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const key of Object.keys(value)) {
      deepFreeze((value as Record<string, unknown>)[key])
    }
    Object.freeze(value)
  }
  return value
}

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

  const immutabilityCases: { name: string; delta: Delta; freshReference: boolean }[] = [
    {
      name: "state",
      delta: {
        type: "state",
        scope: "gateway",
        value: { ...baseTree().gateway, updateAvailable: true },
      },
      freshReference: true,
    },
    {
      name: "agent",
      delta: {
        type: "agent",
        name: "scout",
        info: {
          status: "restarting",
          activityState: "idle",
          buildPhase: null,
          startedAt: null,
          services: {},
        },
      },
      freshReference: true,
    },
    {
      name: "agent_removed",
      delta: { type: "agent_removed", name: "scout" },
      freshReference: true,
    },
    {
      name: "notifications",
      delta: {
        type: "notifications",
        agent: "scout",
        pending: [{ id: 1, type: "notification", source: "sms", summary: "hi" }],
      },
      freshReference: true,
    },
    {
      name: "append",
      delta: { type: "append", agent: "scout", events: [] },
      freshReference: false,
    },
    {
      name: "resync",
      delta: { type: "resync", agent: "scout" },
      freshReference: false,
    },
  ]

  it.each(immutabilityCases)(
    "does not mutate a deep-frozen input tree for a $name delta",
    ({ delta, freshReference }) => {
      const tree = deepFreeze(baseTree())
      let next: Tree | undefined
      expect(() => {
        next = reduceDelta(tree, delta)
      }).not.toThrow()
      if (freshReference) {
        expect(next).not.toBe(tree)
      } else {
        expect(next).toBe(tree)
      }
      expect(Object.isFrozen(tree)).toBe(true)
    },
  )
})
