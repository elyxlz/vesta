import { describe, expect, it } from "vitest";
import type { Room } from "@vesta/core";
import { roomTarget } from "./chats-model";

const direct: Room = {
  id: "dm:aria",
  name: null,
  agents: ["aria"],
  createdAt: 1,
  lastMessageAt: null,
};
const peer: Room = { ...direct, id: "peer-1", agents: ["aria", "nova"] };
const group: Room = {
  ...direct,
  id: "grp-launch",
  name: "Launch week",
  agents: ["aria", "nova"],
};

describe("roomTarget", () => {
  it("sends a direct room to its agent's screen", () => {
    expect(roomTarget(direct)).toEqual({
      pathname: "/agent/[name]",
      params: { name: "aria" },
    });
  });

  it("sends a peer or group room to its own screen", () => {
    expect(roomTarget(peer)).toEqual({
      pathname: "/chat/[roomId]",
      params: { roomId: "peer-1" },
    });
    expect(roomTarget(group)).toEqual({
      pathname: "/chat/[roomId]",
      params: { roomId: "grp-launch" },
    });
  });
});
