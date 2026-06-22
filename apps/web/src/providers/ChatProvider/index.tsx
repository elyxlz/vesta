import { useEffect, useState, type ReactNode } from "react";
import { useChat } from "./use-chat";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useNotifications } from "@/providers/NotificationProvider";
import { useVoice } from "@/stores/use-voice";
import { ChatContext, type ChatContextValue } from "./context";

export { useChatContext } from "./context";

export function ChatProvider({ children }: { children: ReactNode }) {
  const { name, agent, setAgentState } = useSelectedAgent();
  const { speak, prefetch } = useVoice();
  const { notifyAssistant, setChattingAgent } = useNotifications();
  const [showToolCalls, setShowToolCalls] = useState(false);

  useEffect(() => {
    setChattingAgent(name);
    return () => setChattingAgent(null);
  }, [name, setChattingAgent]);

  const ready = agent?.status === "alive";
  const chat = useChat({
    name,
    active: ready,
    onAssistantMessage: (text) => {
      speak(text);
      notifyAssistant(name, text);
    },
    onPrefetch: prefetch,
  });

  useEffect(() => {
    setAgentState(chat.agentState);
  }, [chat.agentState, setAgentState]);

  const value: ChatContextValue = { ...chat, showToolCalls, setShowToolCalls };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
