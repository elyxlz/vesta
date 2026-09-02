import { createContext, useContext } from "react";
import { useAgentSocketState } from "./use-agent-socket";

export type AgentSocketValue = ReturnType<typeof useAgentSocketState>;

export const AgentSocketContext = createContext<AgentSocketValue | null>(null);

export function useAgentSocket() {
  const context = useContext(AgentSocketContext);
  if (!context) {
    throw new Error("useAgentSocket must be used within AgentSocketProvider");
  }
  return context;
}
