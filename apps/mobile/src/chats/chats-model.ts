import { roomKind, type Room } from "@vesta/core";

export type RoomTarget =
  | { pathname: "/agent/[name]"; params: { name: string } }
  | { pathname: "/chat/[roomId]"; params: { roomId: string } };

// A direct room is that agent's own screen; every other room has its own.
export function roomTarget(room: Room): RoomTarget {
  const first = room.agents[0];
  if (roomKind(room) === "direct" && first !== undefined) {
    return { pathname: "/agent/[name]", params: { name: first } };
  }
  return { pathname: "/chat/[roomId]", params: { roomId: room.id } };
}
