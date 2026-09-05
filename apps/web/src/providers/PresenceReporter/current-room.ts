import { directRoomId } from "@vesta/core";

// The conversation a route has open, read off the router's matched params: an agent page reports
// that agent's own direct room (its dashboard, chat, logs, and settings tabs alike), the room
// route reports the room it names, everything else nothing.
export function currentRoom(
  matched: { name?: string; roomId?: string }[],
): string | null {
  for (const params of matched) {
    if (params.roomId !== undefined) return params.roomId;
    if (params.name !== undefined) return directRoomId(params.name);
  }
  return null;
}
