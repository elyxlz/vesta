import type { Room } from "@vesta/core";

// How long a fresh group gets to reach the tree before the screen opens it anyway. The node
// answers the create before /sync carries the room, and the room screen resolves its id off the
// tree, so opening on the answer alone races the delta; a silent socket must not trap the screen
// on its spinner either.
export const ROOM_SETTLE_TIMEOUT_MS = 4000;

// Whether the new-group screen hands over to the room it just opened: as soon as the tree carries
// it, and once the settle window has run out whatever the tree says.
export function newRoomOpens(
  opening: string | null,
  rooms: readonly Room[],
  settled: boolean,
): boolean {
  if (opening === null) return false;
  return settled || rooms.some((room) => room.id === opening);
}
