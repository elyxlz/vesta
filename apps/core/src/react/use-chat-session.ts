import { useSyncExternalStore } from "react";
import type { ChatSession, ChatSessionState } from "../chat/chat-session";
import { initialChatState } from "../chat/chat-stream-model";

const subscribeNothing = (): (() => void) => () => undefined;

const IDLE: ChatSessionState = {
  chat: initialChatState(),
  typing: false,
  loadingMore: false,
  socket: "closed",
  latestReply: null,
  reseedRevision: 0,
};
const idle = (): ChatSessionState => IDLE;

// The live chat session state, re-rendered on every commit. With no session (no agent open, or
// the controller not yet built) the idle state renders an empty, unloaded tail.
export function useChatSession(session: ChatSession | null): ChatSessionState {
  return useSyncExternalStore(
    session?.subscribe ?? subscribeNothing,
    session?.getState ?? idle,
    session?.getState ?? idle,
  );
}
