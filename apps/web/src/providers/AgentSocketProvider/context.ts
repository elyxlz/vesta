import { createContext, useContext } from "react";
import { useAgentSocketState } from "./use-agent-socket";

// Context + hook live here, separate from the AgentSocketProvider component, so the
// AgentSocketContext identity is stable across Fast Refresh. Co-locating them with the
// component made every edit re-create the context, detaching mounted consumers
// ("useAgentSocket must be used within AgentSocketProvider" on hot reload).
export type AgentSocketValue = ReturnType<typeof useAgentSocketState>;

export const AgentSocketContext = createContext<AgentSocketValue | null>(null);

export function useAgentSocket() {
  const context = useContext(AgentSocketContext);
  if (!context) {
    throw new Error("useAgentSocket must be used within AgentSocketProvider");
  }
  return context;
}
