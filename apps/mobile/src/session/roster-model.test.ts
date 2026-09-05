import { describe, expect, it } from "vitest";
import { directRoomId, type AgentInfo } from "@vesta/core";
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
    operation: null,
    startedAt: "2026-01-01T00:00:00Z",
    services: {},
    ...overrides,
  };
}

function snapshot(names: string[], version = "0.2.0"): RosterSnapshot {
  return {
    agents: names.map((name) => ({ name, ...agentInfo() })),
    rooms: names.map((name) => ({
      id: directRoomId(name),
      name: null,
      agents: [name],
      createdAt: 1_753_900_000,
      lastMessageAt: null,
    })),
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

  // The room screen resolves its id off this list, so it rides the same hold as the agents.
  it("holds the room list across a background/foreground cycle", () => {
    const captured = reconcileRosterHold(
      emptyRosterHold,
      "gw",
      snapshot(["aria"]),
    );
    expect(captured.rooms.map((room) => room.id)).toEqual(["dm:aria"]);
    const held = reconcileRosterHold(captured, "gw", null);
    expect(held.rooms.map((room) => room.id)).toEqual(["dm:aria"]);
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
    expect(switched.rooms).toEqual([]);
    expect(switched.agentsReady).toBe(false);
    expect(switched.connectionKey).toBe("gw-b");
  });
});
