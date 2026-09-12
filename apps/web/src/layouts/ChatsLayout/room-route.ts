import { directRoomAgent, type Room } from "@vesta/core";

// Where a conversation row goes. Wide, every room is selected inside the inbox. Narrow, a direct
// room is its agent's own page and every other room has its own full-page route.
export function roomRoute(room: Room, wide: boolean): string {
  if (wide) return `/chats/${encodeURIComponent(room.id)}`;
  const agent = directRoomAgent(room);
  if (agent !== null) return `/agent/${encodeURIComponent(agent)}/chat`;
  return `/chat/${encodeURIComponent(room.id)}`;
}
