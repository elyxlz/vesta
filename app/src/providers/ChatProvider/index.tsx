import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useChat } from "./use-chat";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/providers/VoiceProvider";

type ChatContextValue = ReturnType<typeof useChat>;

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { name, setAgentState } = useSelectedAgent();
  const { speak } = useVoice();

  const chat = useChat({ name, active: true, onAssistantMessage: speak });

  useEffect(() => {
    setAgentState(chat.agentState);
  }, [chat.agentState, setAgentState]);

  return (
    <ChatContext.Provider value={chat}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within ChatProvider");
  }
  return context;
}
