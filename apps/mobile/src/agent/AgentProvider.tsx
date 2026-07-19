import {
  createContext,
  use,
  useEffect,
  type ReactNode,
} from "react";
import { useLocalSearchParams } from "expo-router";
import { useAgentSocket } from "@/chat/useAgentSocket";
import { ControllerContext } from "@/controller/context";
import { setVisibleAgentSocket } from "@/notifications/foreground-policy";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import type { AgentRow } from "@/session/roster-model";
import { writeLastUsedAgent } from "@/storage/recent-agent";

type AgentSocket = ReturnType<typeof useAgentSocket>;

interface AgentValue {
  name: string;
  agent: AgentRow | null;
  socket: AgentSocket;
}

const AgentContext = createContext<AgentValue | null>(null);

// The disconnected socket served while the controller is torn down (pre-connect / backgrounded):
// no live edge, no history. Foregrounding rebuilds the controller and remounts LiveAgent, which
// re-seeds the tail. Every field matches the live socket's shape so consumers need no null checks.
const DISCONNECTED_SOCKET: AgentSocket = {
  events: [],
  agentState: "idle",
  isTyping: false,
  connected: false,
  historyLoaded: false,
  pendingNotifications: [],
  latestLiveChat: null,
  hasMore: false,
  loadingMore: false,
  loadMore: async () => undefined,
  send: () => false,
  retry: () => undefined,
  reseedRevision: 0,
};

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

function LiveAgent({
  name,
  agent,
  active,
  children,
}: {
  name: string;
  agent: AgentRow | null;
  active: boolean;
  children: ReactNode;
}) {
  const socket = useAgentSocket(name, active);
  return (
    <AgentContent name={name} agent={agent} socket={socket}>
      {children}
    </AgentContent>
  );
}

// Tolerates the null controller context (pre-connect / backgrounded): read it nullable rather than
// useController(), which throws when there is no live controller. LiveAgent runs the view-model only
// when the controller exists; otherwise the disconnected socket keeps the surface intact.
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

  useEffect(() => {
    if (name) void writeLastUsedAgent(name);
  }, [name]);

  if (!controller) {
    return (
      <AgentContent name={name} agent={agent} socket={DISCONNECTED_SOCKET}>
        {children}
      </AgentContent>
    );
  }
  return (
    <LiveAgent name={name} agent={agent} active={Boolean(name && connectable)}>
      {children}
    </LiveAgent>
  );
}

export function useAgent(): AgentValue {
  const value = use(AgentContext);
  if (!value) throw new Error("useAgent must be used within AgentProvider");
  return value;
}
