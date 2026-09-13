import { createContext, use } from "react";
import type { AgentRow, RoomKind } from "@vesta/core";
import type { RoomSocket } from "@/chat/useRoomSocket";

// One conversation as the chat surface reads it. AgentProvider builds it for an agent's own direct
// room, RoomProvider for every other room, so one ChatPage serves both.
export interface ChatContextValue {
  roomId: string;
  // The one name this conversation is titled and addressed by.
  label: string;
  // The members that answer in it, in the order the node lists them.
  agents: string[];
  kind: RoomKind;
  // The agent a direct room belongs to, null in a peer or group room (and while an agent page is
  // open for a name the roster does not carry).
  agent: AgentRow | null;
  socket: RoomSocket;
}

export const ChatContext = createContext<ChatContextValue | null>(null);

export function useChat(): ChatContextValue {
  const value = use(ChatContext);
  if (!value) throw new Error("useChat must be used within a chat provider");
  return value;
}
