import { createContext, use, useState, type ReactNode } from "react";
import { emptyChatHold, type ChatHold } from "./chat-hold-model";

// The chat hold lives ABOVE ControllerProvider: the chat view-model (LiveAgent) remounts on every
// background/foreground (the controller flips null), so a hold kept inside it would reset and blank
// the conversation. One in-memory cell, keyed to agent + gateway; a mismatched read clears it.
function createChatHoldStore() {
  let hold: ChatHold = emptyChatHold;
  return {
    read: (): ChatHold => hold,
    persist: (next: ChatHold): void => {
      hold = next;
    },
  };
}

export type ChatHoldStore = ReturnType<typeof createChatHoldStore>;

const ChatHoldContext = createContext<ChatHoldStore | null>(null);

export function ChatHoldProvider({ children }: { children: ReactNode }) {
  const [store] = useState(createChatHoldStore);
  return (
    <ChatHoldContext.Provider value={store}>{children}</ChatHoldContext.Provider>
  );
}

export function useChatHold(): ChatHoldStore {
  const store = use(ChatHoldContext);
  if (!store) {
    throw new Error("useChatHold must be used within ChatHoldProvider");
  }
  return store;
}
