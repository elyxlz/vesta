import { createContext, useContext } from "react";
import type { AgentRow, Room, RoomKind } from "@vesta/core";

export interface RoomContextValue {
  roomId: string;
  room: Room;
  kind: RoomKind;
  /** The one name every surface titles this conversation with. */
  label: string;
  /** The members that answer in it, in the order the node lists them. */
  agents: string[];
  /** The agent a direct room belongs to, null in a peer or group room. */
  directAgent: AgentRow | null;
}

export const RoomContext = createContext<RoomContextValue | null>(null);

export function useRoom(): RoomContextValue {
  const context = useContext(RoomContext);
  if (!context) {
    throw new Error("useRoom must be used within RoomProvider");
  }
  return context;
}
