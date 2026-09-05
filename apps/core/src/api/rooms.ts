import type { HistoryPage } from "../chat/chat-stream-model";
import { parseHistoryPage } from "../protocol/parse-chat";
import type { Room } from "../protocol/tree";
import type { HttpClient } from "../transport/http";

// The chat node's REST surface, served by the gateway itself rather than through an agent proxy.
// The room list also rides the /sync tree, so these bodies are the request-shaped view of it.
export interface RoomsResponse {
  rooms: Room[];
}

export interface RoomOpened {
  room: Room;
}

// Intake's ack. `id` is the stored message's id; a retry of an intent already taken answers
// `deduped` instead, so a client reads delivery off the echo either way.
export interface ChatPostAck {
  ok: true;
  id?: number;
  deduped?: boolean;
}

export interface ChatImportAck {
  imported: number;
  skipped: number;
}

export function roomsPath(): string {
  return "/rooms";
}

export function roomHistoryPath(id: string, cursor?: number): string {
  const query = cursor === undefined ? "" : `?cursor=${String(cursor)}`;
  return `/rooms/${encodeURIComponent(id)}/history${query}`;
}

export function roomMessagesPath(id: string): string {
  return `/rooms/${encodeURIComponent(id)}/messages`;
}

// The replay-free live room socket; dialed with the token in the query. Query-free like every
// other socket path here, since `session.websocketUrl` appends its own `?token=`: name the room by
// passing `new URLSearchParams({ room: id })` as that builder's second argument.
export function roomsSocketPath(): string {
  return "/rooms/ws";
}

export async function fetchRoomHistory(
  http: HttpClient,
  id: string,
  cursor?: number,
): Promise<HistoryPage> {
  return parseHistoryPage(
    await http.json<unknown>(roomHistoryPath(id, cursor)),
  );
}
