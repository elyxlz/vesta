import { describe, expect, it } from "vitest"
import type { NotificationEvent } from "../protocol/events"
import type { AgentInfo, GatewayInfo, Tree } from "../protocol/tree"
import { rosterFromTree, rostersEqual } from "./roster"

function gateway(): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 8080,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
  }
}

function agentInfo(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    status: "alive",
    activityState: "idle",
    buildPhase: null,
    startedAt: "2026-01-01T00:00:00Z",
    services: {},
    ...overrides,
  }
}

function tree(agents: Record<string, { info: AgentInfo; pending?: NotificationEvent[] }>): Tree {
  return {
    gateway: gateway(),
    agents: Object.fromEntries(
      Object.entries(agents).map(([name, node]) => [
        name,
        { info: node.info, notifications: { pending: node.pending ?? [] } },
      ]),
    ),
  }
}

const notification: NotificationEvent = {
  id: 1,
  type: "notification",
  source: "chat",
  summary: "hello",
}

describe("rosterFromTree", () => {
  it.each([
    { name: "null tree yields no rows", input: null, expected: [] },
    { name: "empty agents yields no rows", input: tree({}), expected: [] },
  ])("$name", ({ input, expected }) => {
    expect(rosterFromTree(input)).toEqual(expected)
  })

  it("flattens each agent's name and info into a row", () => {
    const rows = rosterFromTree(
      tree({
        aria: { info: agentInfo({ status: "alive" }) },
        nova: { info: agentInfo({ status: "stopped" }) },
      }),
    )
    expect(rows).toEqual([
      { name: "aria", ...agentInfo({ status: "alive" }) },
      { name: "nova", ...agentInfo({ status: "stopped" }) },
    ])
  })
})

describe("rostersEqual", () => {
  it.each([
    {
      name: "identical rosters are equal",
      a: rosterFromTree(tree({ aria: { info: agentInfo() } })),
      b: rosterFromTree(tree({ aria: { info: agentInfo() } })),
      expected: true,
    },
    {
      name: "different length is unequal",
      a: rosterFromTree(tree({ aria: { info: agentInfo() } })),
      b: rosterFromTree(tree({ aria: { info: agentInfo() }, nova: { info: agentInfo() } })),
      expected: false,
    },
    {
      name: "changed status is unequal",
      a: rosterFromTree(tree({ aria: { info: agentInfo({ status: "alive" }) } })),
      b: rosterFromTree(tree({ aria: { info: agentInfo({ status: "stopped" }) } })),
      expected: false,
    },
    {
      name: "changed buildPhase is unequal",
      a: rosterFromTree(tree({ aria: { info: agentInfo({ buildPhase: null }) } })),
      b: rosterFromTree(tree({ aria: { info: agentInfo({ buildPhase: "building" }) } })),
      expected: false,
    },
    {
      name: "changed service revision is unequal",
      a: rosterFromTree(
        tree({ aria: { info: agentInfo({ services: { web: { port: 1, rev: 1 } } }) } }),
      ),
      b: rosterFromTree(
        tree({ aria: { info: agentInfo({ services: { web: { port: 1, rev: 2 } } }) } }),
      ),
      expected: false,
    },
  ])("$name", ({ a, b, expected }) => {
    expect(rostersEqual(a, b)).toBe(expected)
  })

  it("stays equal when only an unrelated notification branch changes", () => {
    const before = rosterFromTree(tree({ aria: { info: agentInfo() } }))
    const after = rosterFromTree(tree({ aria: { info: agentInfo(), pending: [notification] } }))
    expect(rostersEqual(before, after)).toBe(true)
  })
})
