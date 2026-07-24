import { createContext, use, useEffect, type ReactNode } from "react";
import { useLocalSearchParams } from "expo-router";
import { useAgentSocket } from "@/chat/useAgentSocket";
import { ControllerContext } from "@/controller/context";
import { setVisibleAgentSocket } from "@/notifications/foreground-policy";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import type { AgentRow } from "@vesta/core";
import { writeLastUsedAgent } from "@/storage/recent-agent";

type AgentSocket = ReturnType<typeof useAgentSocket>;

interface AgentValue {
  name: string;
  agent: AgentRow | null;
  socket: AgentSocket;
}

const AgentContext = createContext<AgentValue | null>(null);

function AgentContent({
  name,
  agent,
  socket,
  children,
}: {
  name: string;
  agent: AgentRow | null;
  socket: AgentSocket;
  children: ReactNode;
}) {
  const { connection } = useSession();
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

// The provider and socket hook stay mounted across controller epochs. Backgrounding disables the
// live edges without replacing the nested navigation tree, so an open agent sheet retains its state.
export function AgentProvider({ children }: { children: ReactNode }) {
  const parameters = useLocalSearchParams<{ name?: string }>();
  const name = typeof parameters.name === "string" ? parameters.name : "";
  const controller = use(ControllerContext);
  const { agents } = useRoster();
  const agent = agents.find((candidate) => candidate.name === name) ?? null;
  const connectable =
    agent?.status === "alive" ||
    agent?.status === "not_authenticated" ||
    agent?.status === "unprovisioned";
  const socket = useAgentSocket(
    name,
    Boolean(controller && name && connectable),
    controller,
  );

  useEffect(() => {
    if (name) void writeLastUsedAgent(name);
  }, [name]);

  return (
    <AgentContent name={name} agent={agent} socket={socket}>
      {children}
    </AgentContent>
  );
}

export function useAgent(): AgentValue {
  const value = use(AgentContext);
  if (!value) throw new Error("useAgent must be used within AgentProvider");
  return value;
}
