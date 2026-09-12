import { directRoomAgent, type Room } from "@vesta/core";

type RoomTarget =
  | { pathname: "/agent/[name]"; params: { name: string } }
  | { pathname: "/chat/[roomId]"; params: { roomId: string } };

// A direct room is that agent's own screen; every other room has its own.
export function roomTarget(room: Room): RoomTarget {
  const agent = directRoomAgent(room);
  if (agent !== null) {
    return { pathname: "/agent/[name]", params: { name: agent } };
  }
  return { pathname: "/chat/[roomId]", params: { roomId: room.id } };
}
