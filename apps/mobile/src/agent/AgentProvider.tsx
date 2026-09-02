import { createContext, use, useEffect, useMemo, type ReactNode } from "react";
import { useLocalSearchParams } from "expo-router";
import { useAgentSocket } from "@/chat/useAgentSocket";
import { ControllerContext } from "@/controller/context";
import { setVisibleAgentSocket } from "@/notifications/foreground-policy";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import {
  agentIsConnectable,
  type AgentActivityState,
  type AgentRow,
} from "@vesta/core";
import { writeLastUsedAgent } from "@/storage/recent-agent";
import { servedAgentActivity } from "@/chat/agent-activity-model";

type AgentSocket = ReturnType<typeof useAgentSocket>;

interface AgentValue {
  name: string;
  agent: AgentRow | null;
  activityState: AgentActivityState;
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
  const activityState = servedAgentActivity(
    {
      state: socket.agentState,
      ready: socket.agentStateReady,
    },
    agent?.activityState,
  );
  useEffect(
    () => setVisibleAgentSocket(connection?.url ?? "", name, socket.connected),
    [connection?.url, name, socket.connected],
  );
  // Memoized (with the socket hook's own memoized return) so the four always-mounted agent pages
  // re-render only when a consumed field changes, not on every provider render.
  const value = useMemo(
    () => ({ name, agent, activityState, socket }),
    [name, agent, activityState, socket],
  );
  return (
    <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
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
  const connectable = agent !== null && agentIsConnectable(agent.status);
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
