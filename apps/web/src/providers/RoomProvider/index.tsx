import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { roomKind, roomLabel } from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { RoomContext, type RoomContextValue } from "./context";

// One conversation, resolved off the node's room list. Every chat surface hangs under this: the
// agent page instantiates it with that agent's own direct room, the room route with any id.
export function RoomProvider({
  roomId,
  children,
}: {
  roomId: string;
  children: ReactNode;
}) {
  const { rooms, agents, agentsFetched } = useGateway();
  const room = rooms.find((candidate) => candidate.id === roomId);

  // Before the snapshot lands the room list is unknown, not empty; only a loaded tree that does
  // not carry this id means the conversation is gone.
  if (!room) {
    return agentsFetched ? <Navigate to="/" replace /> : null;
  }

  const kind = roomKind(room);
  const value: RoomContextValue = {
    roomId,
    room,
    kind,
    label: roomLabel(room),
    agents: room.agents,
    directAgent:
      kind === "direct"
        ? (agents.find((row) => row.name === room.agents[0]) ?? null)
        : null,
  };

  return <RoomContext.Provider value={value}>{children}</RoomContext.Provider>;
}
