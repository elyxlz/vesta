import { directRoomId } from "@vesta/core";

// The conversation this app has open, read off the router's own segments and params: an agent page
// reports that agent's direct room (its chat, dashboard, logs, and settings alike), the room screen
// reports the room it names, everywhere else nothing.
export function currentRoom(
  segments: readonly string[],
  params: { name?: string; roomId?: string },
): string | null {
  if (segments[0] === "chat" && params.roomId !== undefined) {
    return params.roomId;
  }
  if (segments[0] === "agent" && params.name !== undefined) {
    return directRoomId(params.name);
  }
  return null;
}
