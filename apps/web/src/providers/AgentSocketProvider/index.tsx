import { useEffect, type ReactNode } from "react";
import { useAgentSocketState } from "./use-agent-socket";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useNotifications } from "@/providers/NotificationProvider";
import { useVoice } from "@/stores/use-voice";
import { AgentSocketContext, type AgentSocketValue } from "./context";
import { agentIsConnectable } from "@vesta/core";

export { useAgentSocket } from "./context";

export function AgentSocketProvider({ children }: { children: ReactNode }) {
  const { name, agent, setAgentState } = useSelectedAgent();
  const { speak, prefetch } = useVoice();
  const { notifyAssistant, setChattingAgent } = useNotifications();

  useEffect(() => {
    setChattingAgent(name);
    return () => setChattingAgent(null);
  }, [name, setChattingAgent]);

  // Connect once the agent's WS is up so chat history loads — including when the
  // agent isn't authenticated yet (the composer stays disabled until sign-in).
  const connectable = agentIsConnectable(agent.status);
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

  const value: AgentSocketValue = { ...socket };

  return (
    <AgentSocketContext.Provider value={value}>
      {children}
    </AgentSocketContext.Provider>
  );
}
