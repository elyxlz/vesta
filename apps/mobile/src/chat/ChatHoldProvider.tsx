import { createContext, use, useState, type ReactNode } from "react";
import { emptyChatHold, type ChatHold } from "./chat-hold-model";

// The chat hold lives above the controller epoch and preserves the last committed conversation
// through socket rebuilds or agent-surface remounts. It is keyed to agent + gateway, and a
// mismatched read clears it so one conversation can never bleed into another.
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
    <ChatHoldContext.Provider value={store}>
      {children}
    </ChatHoldContext.Provider>
  );
}

export function useChatHold(): ChatHoldStore {
  const store = use(ChatHoldContext);
  if (!store) {
    throw new Error("useChatHold must be used within ChatHoldProvider");
  }
  return store;
}
