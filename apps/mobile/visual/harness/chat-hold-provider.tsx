import { createContext, use, useState, type ReactNode } from "react";
import {
  initialChatState,
  seedTail,
  type ChatState,
} from "@vesta/core";
import {
  captureChatHold,
  chatHoldKey,
  type ChatHold,
} from "../../src/chat/chat-hold-model";
import { connectionKeyOf } from "../../src/session/session-model";
import { visualConnection } from "./session-provider";

interface ChatHoldStore {
  read: () => ChatHold;
  persist: (next: ChatHold) => void;
}

const chatState: ChatState = seedTail(initialChatState(), {
  events: [
    {
      id: 101,
      type: "user",
      text: "What should I focus on before tomorrow's product review?",
      ts: "2026-08-01T09:18:00.000Z",
    },
    {
      id: 102,
      type: "chat",
      text: "The onboarding polish and mobile QA gaps are the two items most likely to unblock the review.",
      ts: "2026-08-01T09:18:14.000Z",
    },
    {
      id: 103,
      type: "user",
      text: "Turn that into a short checklist.",
      ts: "2026-08-01T09:19:00.000Z",
    },
    {
      id: 104,
      type: "chat",
      text: "Done. I prioritized the visual regressions first, then the demo notes and follow-ups.",
      ts: "2026-08-01T09:19:11.000Z",
    },
  ],
  cursor: null,
});

function createVisualChatHoldStore(): ChatHoldStore {
  let hold = captureChatHold(
    chatHoldKey("aria", connectionKeyOf(visualConnection) ?? ""),
    chatState,
  );
  return {
    read: () => hold,
    persist: (next) => {
      hold = next;
    },
  };
}

const ChatHoldContext = createContext<ChatHoldStore | null>(null);

export function ChatHoldProvider({ children }: { children: ReactNode }) {
  const [store] = useState(createVisualChatHoldStore);
  return (
    <ChatHoldContext.Provider value={store}>
      {children}
    </ChatHoldContext.Provider>
  );
}

export function useChatHold(): ChatHoldStore {
  const store = use(ChatHoldContext);
  if (!store) throw new Error("useChatHold must be used within ChatHoldProvider");
  return store;
}
