import { describe, expect, it } from "vitest";
import type {
  AgentInfo,
  GatewayInfo,
  NotificationEvent,
  Tree,
} from "@vesta/core";
import {
  emptyRosterHold,
  reconcileRosterHold,
  rosterFromTree,
  rostersEqual,
  type RosterSnapshot,
} from "./roster-model";

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
  };
}

function agentInfo(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    status: "alive",
    activityState: "idle",
    buildPhase: null,
    startedAt: "2026-01-01T00:00:00Z",
    services: {},
    ...overrides,
  };
}

function tree(
  agents: Record<string, { info: AgentInfo; pending?: NotificationEvent[] }>,
): Tree {
  return {
    gateway: gateway(),
    agents: Object.fromEntries(
      Object.entries(agents).map(([name, node]) => [
        name,
        { info: node.info, notifications: { pending: node.pending ?? [] } },
      ]),
    ),
  };
}

const notification: NotificationEvent = {
  id: 1,
  type: "notification",
  source: "chat",
  summary: "hello",
};

describe("rosterFromTree", () => {
  it.each([
    { name: "null tree yields no rows", input: null, expected: [] },
    {
      name: "empty agents yields no rows",
      input: tree({}),
      expected: [],
    },
  ])("$name", ({ input, expected }) => {
    expect(rosterFromTree(input)).toEqual(expected);
  });

  it("flattens each agent's name and info into a row", () => {
    const rows = rosterFromTree(
      tree({
        aria: { info: agentInfo({ status: "alive" }) },
        nova: { info: agentInfo({ status: "stopped" }) },
      }),
    );
    expect(rows).toEqual([
      { name: "aria", ...agentInfo({ status: "alive" }) },
      { name: "nova", ...agentInfo({ status: "stopped" }) },
    ]);
  });
});

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
      b: rosterFromTree(
        tree({ aria: { info: agentInfo() }, nova: { info: agentInfo() } }),
      ),
      expected: false,
    },
    {
      name: "changed status is unequal",
      a: rosterFromTree(tree({ aria: { info: agentInfo({ status: "alive" }) } })),
      b: rosterFromTree(
        tree({ aria: { info: agentInfo({ status: "stopped" }) } }),
      ),
      expected: false,
    },
  ])("$name", ({ a, b, expected }) => {
    expect(rostersEqual(a, b)).toBe(expected);
  });

  it("stays equal when only an unrelated notification branch changes", () => {
    const before = rosterFromTree(tree({ aria: { info: agentInfo() } }));
    const after = rosterFromTree(
      tree({ aria: { info: agentInfo(), pending: [notification] } }),
    );
    expect(rostersEqual(before, after)).toBe(true);
  });
});

function snapshot(names: string[], version = "0.2.0"): RosterSnapshot {
  return {
    agents: names.map((name) => ({ name, ...agentInfo() })),
    gatewayVersion: version,
    managed: false,
    updateAvailable: false,
    latestVersion: null,
  };
}

describe("reconcileRosterHold", () => {
  it("holds the last-known roster across a background/foreground cycle", () => {
    const captured = reconcileRosterHold(emptyRosterHold, "gw", snapshot(["aria"]));
    expect(captured.agents.map((row) => row.name)).toEqual(["aria"]);
    expect(captured.agentsReady).toBe(true);

    // Controller torn down on background: no fresh snapshot, same gateway -> the roster is retained.
    const held = reconcileRosterHold(captured, "gw", null);
    expect(held.agents.map((row) => row.name)).toEqual(["aria"]);
    expect(held.agentsReady).toBe(true);

    // Foreground snapshot lands and replaces the held roster.
    const refreshed = reconcileRosterHold(held, "gw", snapshot(["aria", "nova"]));
    expect(refreshed.agents.map((row) => row.name)).toEqual(["aria", "nova"]);
  });

  it("clears the hold on a gateway change so no agents bleed across", () => {
    const onGatewayA = reconcileRosterHold(
      emptyRosterHold,
      "gw-a",
      snapshot(["aria"]),
    );
    // New gateway, snapshot not yet arrived: the prior gateway's roster must not be served.
    const switched = reconcileRosterHold(onGatewayA, "gw-b", null);
    expect(switched.agents).toEqual([]);
    expect(switched.agentsReady).toBe(false);
    expect(switched.connectionKey).toBe("gw-b");
  });
});
