import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import { roomRoute } from "./room-route";

const direct: Room = {
  id: "dm:luna",
  name: null,
  agents: ["luna"],
  createdAt: 1_755_000_000,
  lastMessageAt: null,
};
const peer: Room = { ...direct, id: "peer-1", agents: ["atlas", "iris"] };
const group: Room = {
  ...direct,
  id: "grp-trip",
  name: "lisbon trip",
  agents: ["luna", "atlas"],
};

describe("roomRoute", () => {
  it("selects any room inside the inbox at wide width", () => {
    expect(roomRoute(direct, true)).toBe("/chats/dm%3Aluna");
    expect(roomRoute(group, true)).toBe("/chats/grp-trip");
  });

  it("opens a direct room on its agent's page at narrow width", () => {
    expect(roomRoute(direct, false)).toBe("/agent/luna/chat");
  });

  it("opens a peer or group room on its own page at narrow width", () => {
    expect(roomRoute(peer, false)).toBe("/chat/peer-1");
    expect(roomRoute(group, false)).toBe("/chat/grp-trip");
  });
});
