import type { Room } from "@vesta/core";

// What the room screen shows for the id it routed to, read off the held room list. A tree that has
// not loaded is unknown, not empty, so a controller epoch (backgrounding closes the controller)
// keeps the open conversation on screen; only a loaded tree that lacks the id means the room is
// gone (deleted elsewhere, or a stale deep link).
export type RoomResolution =
  { state: "room"; room: Room } | { state: "unknown" } | { state: "gone" };

export function resolveRoom(
  rooms: readonly Room[],
  roomsReady: boolean,
  roomId: string,
): RoomResolution {
  const room = rooms.find((candidate) => candidate.id === roomId);
  if (room) return { state: "room", room };
  return roomsReady ? { state: "gone" } : { state: "unknown" };
}
