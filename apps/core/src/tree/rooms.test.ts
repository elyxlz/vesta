import { describe, expect, it } from "vitest";
import type { Room, Tree } from "../protocol/tree";
import {
  directRoomId,
  roomKind,
  roomLabel,
  roomsEqual,
  selectRooms,
} from "./rooms";

function room(overrides: Partial<Room> = {}): Room {
  return {
    id: "dm:ada",
    name: null,
    agents: ["ada"],
    createdAt: 1_700_000_000,
    lastMessageAt: null,
    ...overrides,
  };
}

function treeWith(rooms: Room[]): Tree {
  return { gateway: {}, agents: {}, devices: [], rooms } as unknown as Tree;
}

describe("roomKind", () => {
  it("reads one unnamed agent as a direct room", () => {
    expect(roomKind(room())).toBe("direct");
  });

  it("reads two unnamed agents as a peer room", () => {
    expect(roomKind(room({ id: "peer-1", agents: ["ada", "ben"] }))).toBe(
      "peer",
    );
  });

  it("reads any named room as a group, whatever its size", () => {
    expect(roomKind(room({ name: "Ops" }))).toBe("group");
    expect(roomKind(room({ name: "Ops", agents: ["ada", "ben"] }))).toBe(
      "group",
    );
  });

  it("reads three or more agents as a group even unnamed", () => {
    expect(roomKind(room({ agents: ["ada", "ben", "cy"] }))).toBe("group");
  });
});

describe("roomLabel", () => {
  it("names a direct room after its agent", () => {
    expect(roomLabel(room())).toBe("ada");
  });

  it("joins the two agents of a peer room", () => {
    expect(roomLabel(room({ agents: ["ada", "ben"] }))).toBe("ada & ben");
  });

  it("names a group room after itself", () => {
    expect(roomLabel(room({ name: "Ops", agents: ["ada", "ben"] }))).toBe(
      "Ops",
    );
  });
});

describe("directRoomId", () => {
  it("addresses an agent's direct room", () => {
    expect(directRoomId("ada")).toBe("dm:ada");
  });
});

describe("selectRooms", () => {
  it("returns an empty list for a null tree", () => {
    expect(selectRooms(null)).toEqual([]);
  });

  it("orders by the newest message, then by label, with the empty rooms last", () => {
    const rooms = [
      room({ id: "dm:zed", agents: ["zed"], lastMessageAt: null }),
      room({ id: "dm:ada", agents: ["ada"], lastMessageAt: 1_700_000_100 }),
      room({ id: "dm:ben", agents: ["ben"], lastMessageAt: null }),
      room({ id: "grp-1", name: "Ops", lastMessageAt: 1_700_000_900 }),
    ];
    expect(selectRooms(treeWith(rooms)).map((entry) => entry.id)).toEqual([
      "grp-1",
      "dm:ada",
      "dm:ben",
      "dm:zed",
    ]);
  });

  it("leaves the tree's own list untouched", () => {
    const rooms = [
      room({ id: "dm:zed", agents: ["zed"], lastMessageAt: null }),
      room({ id: "dm:ada", agents: ["ada"], lastMessageAt: 1 }),
    ];
    selectRooms(treeWith(rooms));
    expect(rooms.map((entry) => entry.id)).toEqual(["dm:zed", "dm:ada"]);
  });
});

describe("roomsEqual", () => {
  it("is true for structurally identical lists", () => {
    expect(roomsEqual([room()], [room()])).toBe(true);
  });

  it("is false when a field differs", () => {
    expect(roomsEqual([room()], [room({ lastMessageAt: 5 })])).toBe(false);
    expect(roomsEqual([room()], [room({ name: "Ops" })])).toBe(false);
    expect(roomsEqual([room()], [room({ agents: ["ada", "ben"] })])).toBe(
      false,
    );
  });

  it("is false when the lengths differ", () => {
    expect(roomsEqual([room()], [])).toBe(false);
  });
});
