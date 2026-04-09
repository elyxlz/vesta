import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { listAgents } from "@/api";
import { wsUrl } from "@/lib/connection";
import type { AgentActivityState, ListEntry } from "@/lib/types";
import { useAuth } from "@/providers/AuthProvider";

const POLL_INTERVAL = 5000;

interface AgentsContextValue {
  agents: ListEntry[];
  agentsLoaded: boolean;
  activityStates: Record<string, AgentActivityState>;
  setAgents: Dispatch<SetStateAction<ListEntry[]>>;
  refreshAgents: () => Promise<ListEntry[]>;
}

const AgentsContext = createContext<AgentsContextValue | null>(null);

const noopSetAgents: Dispatch<SetStateAction<ListEntry[]>> = () => {};
const noopRefresh = async () => [] as ListEntry[];

function ConnectedAgentsProvider({ children }: { children: ReactNode }) {
  const { setReachable } = useAuth();
  const [agents, setAgents] = useState<ListEntry[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);
  const [activityStates, setActivityStates] = useState<
    Record<string, AgentActivityState>
  >({});
  const wsRefs = useRef<Map<string, WebSocket>>(new Map());

  const refreshAgents = useCallback(async () => {
    try {
      const nextAgents = await listAgents();
      setAgents(nextAgents);
      setAgentsLoaded(true);
      setReachable(true);
      return nextAgents;
    } catch {
      setAgentsLoaded(true);
      setReachable(false);
      return [];
    }
  }, [setReachable]);

  useEffect(() => {
    void refreshAgents();
    const interval = setInterval(() => void refreshAgents(), POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [refreshAgents]);

  useEffect(() => {
    const aliveNames = new Set(
      agents.filter((a) => a.alive).map((a) => a.name),
    );
    const current = wsRefs.current;

    for (const [name, ws] of current.entries()) {
      if (!aliveNames.has(name)) {
        ws.close();
        current.delete(name);
      }
    }

    for (const name of aliveNames) {
      if (current.has(name)) continue;
      try {
        const ws = new WebSocket(wsUrl(name));
        current.set(name, ws);
        ws.onmessage = (e) => {
          if (typeof e.data !== "string") return;
          try {
            const data = JSON.parse(e.data);
            if (
              (data.type === "status" || data.type === "history") &&
              data.state
            ) {
              setActivityStates((prev) => ({ ...prev, [name]: data.state }));
            }
          } catch {
            // ignore
          }
        };
        ws.onclose = () => {
          current.delete(name);
        };
      } catch {
        // ignore ws errors
      }
    }
  }, [agents]);

  useEffect(() => {
    return () => {
      for (const ws of wsRefs.current.values()) ws.close();
      wsRefs.current.clear();
    };
  }, []);

  const value = useMemo(
    () => ({ agents, agentsLoaded, activityStates, setAgents, refreshAgents }),
    [agents, agentsLoaded, activityStates, refreshAgents],
  );

  return (
    <AgentsContext.Provider value={value}>{children}</AgentsContext.Provider>
  );
}

const disconnectedValue: AgentsContextValue = {
  agents: [],
  agentsLoaded: false,
  activityStates: {},
  setAgents: noopSetAgents,
  refreshAgents: noopRefresh,
};

export function AgentsProvider({ children }: { children: ReactNode }) {
  const { connected, initialized } = useAuth();

  if (initialized && connected) {
    return <ConnectedAgentsProvider>{children}</ConnectedAgentsProvider>;
  }

  return (
    <AgentsContext.Provider value={disconnectedValue}>
      {children}
    </AgentsContext.Provider>
  );
}

export function useAgents() {
  const context = useContext(AgentsContext);
  if (!context) {
    throw new Error("useAgents must be used within AgentsProvider");
  }
  return context;
}
