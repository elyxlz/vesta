import type { Room, Tree } from "../protocol/tree";

// What a room is, read off its own shape: the direct chat on an agent's page is the room carrying
// that agent's own direct id, one or two agents under any other unnamed id is a peer room, and
// anything named (or larger) is a group. The id is what separates the two unnamed forms, since a
// peer room the user shares with a single agent lists that one agent too.
export type RoomKind = "direct" | "peer" | "group";

export function roomKind(room: Room): RoomKind {
  if (room.name !== null) return "group";
  const [first] = room.agents;
  if (first === undefined) return "group";
  if (room.agents.length === 1) {
    return room.id === directRoomId(first) ? "direct" : "peer";
  }
  return room.agents.length === 2 ? "peer" : "group";
}

// The one name every surface titles a room with: the agent, both agents, or the group's own name.
export function roomLabel(room: Room): string {
  if (room.name !== null) return room.name;
  return room.agents.join(" & ");
}

// An agent's direct room, the id the agent page chats in.
export function directRoomId(agent: string): string {
  return `dm:${agent}`;
}

// The conversation list: the busiest room first, the never-used ones last, ties broken by label so
// the order is stable across snapshots. A room holding no agent has nobody to answer in it, so it
// never reaches a view.
export function selectRooms(tree: Tree | null): Room[] {
  const rooms = (tree?.rooms ?? []).filter((room) => room.agents.length > 0);
  return rooms.sort((left, right) => {
    if (left.lastMessageAt !== right.lastMessageAt) {
      if (left.lastMessageAt === null) return 1;
      if (right.lastMessageAt === null) return -1;
      return right.lastMessageAt - left.lastMessageAt;
    }
    return roomLabel(left).localeCompare(roomLabel(right));
  });
}

// Structural compare so an unrelated tree delta (an agent update, a notification) does not hand
// every room consumer a fresh array through useReplica.
export function roomsEqual(a: Room[], b: Room[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((room, index) => {
    const other = b[index];
    if (other === undefined) return false;
    return (
      other.id === room.id &&
      other.name === room.name &&
      other.createdAt === room.createdAt &&
      other.lastMessageAt === room.lastMessageAt &&
      other.agents.length === room.agents.length &&
      other.agents.every((agent, at) => agent === room.agents[at])
    );
  });
}
