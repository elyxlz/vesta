import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useChat } from "./use-chat";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/providers/VoiceProvider";

type ChatContextValue = ReturnType<typeof useChat> & {
  showToolCalls: boolean;
  setShowToolCalls: Dispatch<SetStateAction<boolean>>;
};

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { name, setAgentState } = useSelectedAgent();
  const { speak } = useVoice();
  const [showToolCalls, setShowToolCalls] = useState(false);

  const chat = useChat({ name, active: true, onAssistantMessage: speak });

  useEffect(() => {
    setAgentState(chat.agentState);
  }, [chat.agentState, setAgentState]);

  const value = useMemo(
    () => ({ ...chat, showToolCalls, setShowToolCalls }),
    [chat, showToolCalls],
  );

  return (
    <ChatContext.Provider value={value}>
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
