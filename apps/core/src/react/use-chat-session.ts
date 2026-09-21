import { useMemo, useSyncExternalStore } from "react";
import type { ChatSession, ChatSessionState } from "../chat/chat-session";
import { initialChatState, type ChatState } from "../chat/chat-stream-model";

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

// The live chat session state, re-rendered on every commit. With no session (no agent open, the
// controller not yet built, or the gap between two controller epochs) the held tail renders when
// the caller has one, so a backgrounded chat never blanks to a skeleton; otherwise an empty,
// unloaded tail.
export function useChatSession(
  session: ChatSession | null,
  held: ChatState | null = null,
): ChatSessionState {
  const state = useSyncExternalStore(
    session?.subscribe ?? subscribeNothing,
    session?.getState ?? idle,
    session?.getState ?? idle,
  );
  return useMemo(
    () => (session === null && held !== null ? { ...IDLE, chat: held } : state),
    [session, held, state],
  );
}
