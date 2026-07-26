import { describe, expect, it } from "vitest";
import type { AgentInfo } from "@vesta/core";
import {
  emptyRosterHold,
  reconcileRosterHold,
  type RosterSnapshot,
} from "./roster-model";

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

function snapshot(names: string[], version = "0.2.0"): RosterSnapshot {
  return {
    agents: names.map((name) => ({ name, ...agentInfo() })),
    gatewayVersion: version,
    gatewayChannel: "stable",
    managed: false,
    updateAvailable: false,
    latestVersion: null,
  };
}

describe("reconcileRosterHold", () => {
  it("holds the last-known roster across a background/foreground cycle", () => {
    const captured = reconcileRosterHold(
      emptyRosterHold,
      "gw",
      snapshot(["aria"]),
    );
    expect(captured.agents.map((row) => row.name)).toEqual(["aria"]);
    expect(captured.agentsReady).toBe(true);

    // Controller torn down on background: no fresh snapshot, same gateway -> the roster is retained.
    const held = reconcileRosterHold(captured, "gw", null);
    expect(held.agents.map((row) => row.name)).toEqual(["aria"]);
    expect(held.agentsReady).toBe(true);

    // Foreground snapshot lands and replaces the held roster.
    const refreshed = reconcileRosterHold(
      held,
      "gw",
      snapshot(["aria", "nova"]),
    );
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
