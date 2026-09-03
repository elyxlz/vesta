import { createContext, useContext } from "react";
import type { LogSession } from "@/lib/log-session";

export const AgentLogSessionContext = createContext<LogSession | null>(null);

export function useAgentLogSession(): LogSession {
  const session = useContext(AgentLogSessionContext);
  if (!session) {
    throw new Error(
      "useAgentLogSession must be used within AgentLogStreamProvider",
    );
  }
  return session;
}
