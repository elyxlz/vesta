import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import { newRoomOpens, ROOM_SETTLE_TIMEOUT_MS } from "./new-room-model";

const group: Room = {
  id: "grp-trip",
  name: "Trip planning",
  agents: ["aria", "nova"],
  createdAt: 1_754_000_000,
  lastMessageAt: null,
};

describe("newRoomOpens", () => {
  it("stays put while no group has been created", () => {
    expect(newRoomOpens(null, [group], false)).toBe(false);
  });

  it("opens the room the tree carries", () => {
    expect(newRoomOpens("grp-trip", [group], false)).toBe(true);
  });

  it("waits while the tree has not caught up", () => {
    expect(newRoomOpens("grp-trip", [], false)).toBe(false);
  });

  // A silent socket would otherwise leave the screen spinning on its Create button forever.
  it("opens the room anyway once the settle window has run out", () => {
    expect(newRoomOpens("grp-trip", [], true)).toBe(true);
  });

  it("gives the tree the same window the web dialog does", () => {
    expect(ROOM_SETTLE_TIMEOUT_MS).toBe(4000);
  });
});
