import { useEffect, useState, type ReactNode } from "react";
import { useAgentSocketState } from "./use-agent-socket";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useNotifications } from "@/providers/NotificationProvider";
import { useVoice } from "@/stores/use-voice";
import { AgentSocketContext, type AgentSocketValue } from "./context";

export { useAgentSocket } from "./context";

export function AgentSocketProvider({ children }: { children: ReactNode }) {
  const { name, agent, setAgentState } = useSelectedAgent();
  const { speak, prefetch } = useVoice();
  const { notifyAssistant, setChattingAgent } = useNotifications();
  const [showToolCalls, setShowToolCalls] = useState(false);

  useEffect(() => {
    setChattingAgent(name);
    return () => setChattingAgent(null);
  }, [name, setChattingAgent]);

  // Connect once the agent's WS is up so chat history loads — including when the
  // agent isn't authenticated yet (the composer stays disabled until sign-in).
  const connectable =
    agent?.status === "alive" ||
    agent?.status === "not_authenticated" ||
    agent?.status === "unprovisioned";
  const socket = useAgentSocketState({
    name,
    active: connectable,
    onAssistantMessage: (text) => {
      speak(text);
      notifyAssistant(name, text);
    },
    onPrefetch: prefetch,
  });

  useEffect(() => {
    setAgentState(socket.agentState);
  }, [socket.agentState, setAgentState]);

  const value: AgentSocketValue = {
    ...socket,
    showToolCalls,
    setShowToolCalls,
  };

  return (
    <AgentSocketContext.Provider value={value}>
      {children}
    </AgentSocketContext.Provider>
  );
}
