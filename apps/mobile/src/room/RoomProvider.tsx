import { use, useMemo, type ReactNode } from "react";
import { Redirect } from "expo-router";
import { roomKind, roomLabel, type Room } from "@vesta/core";
import { ChatContext, type ChatContextValue } from "@/chat/chat-context";
import { useRoomSocket } from "@/chat/useRoomSocket";
import { ControllerContext } from "@/controller/context";
import { useRoster } from "@/session/RosterProvider";

// One conversation off the node's room list, for every room that is not an agent's own: the room
// screen instantiates it with the id it routed to.
export function RoomProvider({
  roomId,
  children,
}: {
  roomId: string;
  children: ReactNode;
}) {
  const { rooms, agentsReady } = useRoster();
  const room = rooms.find((candidate) => candidate.id === roomId);

  // Before the snapshot lands the room list is unknown, not empty; only a loaded tree that does
  // not carry this id means the conversation is gone (deleted elsewhere, or a stale deep link).
  if (!room) return agentsReady ? <Redirect href="/" /> : null;
  return <RoomChat room={room}>{children}</RoomChat>;
}

function RoomChat({ room, children }: { room: Room; children: ReactNode }) {
  const controller = use(ControllerContext);
  const { agents } = useRoster();
  const kind = roomKind(room);
  const first = room.agents[0];
  const directAgent =
    kind === "direct" && first !== undefined
      ? (agents.find((row) => row.name === first) ?? null)
      : null;
  const socket = useRoomSocket(room.id, directAgent?.name ?? null, controller);
  const value = useMemo<ChatContextValue>(
    () => ({
      roomId: room.id,
      label: roomLabel(room),
      agents: room.agents,
      kind,
      agent: directAgent,
      socket,
    }),
    [room, kind, directAgent, socket],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
