import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import {
  emptyRosterHold,
  reconcileRosterHold,
  type RosterSnapshot,
} from "@/session/roster-model";
import { resolveRoom } from "./room-resolution";

const group: Room = {
  id: "grp-trip",
  name: "Trip planning",
  agents: ["aria", "nova"],
  createdAt: 1_754_000_000,
  lastMessageAt: 1_754_038_800,
};

function snapshot(rooms: Room[]): RosterSnapshot {
  return {
    agents: [],
    rooms,
    gatewayVersion: "0.2.0",
    gatewayChannel: "stable",
    managed: false,
    updateAvailable: false,
    latestVersion: null,
  };
}

describe("resolveRoom", () => {
  it("resolves the room the node carries", () => {
    expect(resolveRoom([group], true, "grp-trip")).toEqual({
      state: "room",
      room: group,
    });
  });

  it("waits while the tree has not loaded", () => {
    expect(resolveRoom([], false, "grp-trip")).toEqual({ state: "unknown" });
  });

  it("sends an unknown id home once the tree has loaded", () => {
    expect(resolveRoom([group], true, "grp-gone")).toEqual({ state: "gone" });
  });

  // Backgrounding tears the controller down, so the live room list reads empty; the hold is what
  // keeps the open conversation on screen instead of bouncing it Home.
  it("keeps the open room across a controller epoch", () => {
    const captured = reconcileRosterHold(
      emptyRosterHold,
      "gw",
      snapshot([group]),
    );
    const held = reconcileRosterHold(captured, "gw", null);
    expect(resolveRoom(held.rooms, held.agentsReady, "grp-trip")).toEqual({
      state: "room",
      room: group,
    });
  });

  // A different gateway drops the prior node's rooms, so the screen waits for the new tree and
  // only then sends a room that node does not carry Home.
  it("sends the room home on a gateway change once the new tree has loaded", () => {
    const captured = reconcileRosterHold(
      emptyRosterHold,
      "gw-a",
      snapshot([group]),
    );
    const switched = reconcileRosterHold(captured, "gw-b", null);
    expect(
      resolveRoom(switched.rooms, switched.agentsReady, "grp-trip"),
    ).toEqual({ state: "unknown" });
    const loaded = reconcileRosterHold(switched, "gw-b", snapshot([]));
    expect(resolveRoom(loaded.rooms, loaded.agentsReady, "grp-trip")).toEqual({
      state: "gone",
    });
  });
});
