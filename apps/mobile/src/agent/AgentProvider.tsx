import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useLocalSearchParams } from "expo-router";
import type { AgentInfo } from "@/api/types";
import { useAgentSocket } from "@/chat/useAgentSocket";
import { setVisibleAgentSocket } from "@/notifications/foreground-policy";
import { useSession } from "@/session/SessionProvider";
import { writeLastUsedAgent } from "@/storage/recent-agent";

type AgentSocket = ReturnType<typeof useAgentSocket>;

interface AgentValue {
  name: string;
  agent: AgentInfo | null;
  socket: AgentSocket;
}

const AgentContext = createContext<AgentValue | null>(null);

export function AgentProvider({ children }: { children: ReactNode }) {
  const parameters = useLocalSearchParams<{ name?: string }>();
  const name = typeof parameters.name === "string" ? parameters.name : "";
  const { agents, connection } = useSession();
  const agent = agents.find((candidate) => candidate.name === name) ?? null;
  const connectable =
    agent?.status === "alive" ||
    agent?.status === "not_authenticated" ||
    agent?.status === "unprovisioned";
  const socket = useAgentSocket(name, Boolean(name && connectable));

  useEffect(() => {
    if (name) void writeLastUsedAgent(name);
  }, [name]);

  useEffect(
    () => setVisibleAgentSocket(connection?.url ?? "", name, socket.connected),
    [connection?.url, name, socket.connected],
  );

  return (
    <AgentContext.Provider value={{ name, agent, socket }}>
      {children}
    </AgentContext.Provider>
  );
}

export function useAgent(): AgentValue {
  const value = useContext(AgentContext);
  if (!value) throw new Error("useAgent must be used within AgentProvider");
  return value;
}
