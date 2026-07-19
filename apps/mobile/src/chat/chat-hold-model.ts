import type { ConnectionConfig } from "@/api/types";
import type { ChatState } from "./chat-stream-model";

// A single stale-while-reconnecting cell for the chat tail, held ABOVE the controller so it survives
// the controller epoch (background tears the controller down and unmounts the chat view-model). It
// carries the whole render slice of ChatState (messages, cursor, historyLoaded, shownIds,
// pendingIntents); the transient typing queue is deliberately not held.
export interface ChatHold {
  key: string;
  state: ChatState | null;
}

export const emptyChatHold: ChatHold = { key: "", state: null };

// Chat is per-agent AND per-gateway: the key pins the held tail to both so a different agent or a
// switched gateway never seeds the wrong conversation.
export function connectionKeyOf(connection: ConnectionConfig | null): string {
  return connection ? `${connection.url}\n${String(connection.hosted)}` : "";
}

export function chatHoldKey(agent: string, connectionKey: string): string {
  return `${agent}\n${connectionKey}`;
}

// The held ChatState for THIS key, or null when the key changed (a different agent or gateway). The
// clear is synchronous at the read, so the prior conversation never bleeds into the next for a frame.
export function heldChatState(hold: ChatHold, key: string): ChatState | null {
  return hold.key === key ? hold.state : null;
}

export function captureChatHold(key: string, state: ChatState): ChatHold {
  return { key, state };
}
