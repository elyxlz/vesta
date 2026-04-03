import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { listAgents } from "@/api";
import type { ListEntry } from "@/lib/types";
import { useAuth } from "@/providers/AuthProvider";

interface AgentsContextValue {
  agents: ListEntry[];
  agentsLoaded: boolean;
  setAgents: Dispatch<SetStateAction<ListEntry[]>>;
  refreshAgents: () => Promise<ListEntry[]>;
}

const AgentsContext = createContext<AgentsContextValue | null>(null);

const noopSetAgents: Dispatch<SetStateAction<ListEntry[]>> = () => {};
const noopRefresh = async () => [] as ListEntry[];

function ConnectedAgentsProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<ListEntry[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);

  const refreshAgents = useCallback(async () => {
    try {
      const nextAgents = await listAgents();
      setAgents(nextAgents);
      setAgentsLoaded(true);
      return nextAgents;
    } catch {
      setAgents([]);
      setAgentsLoaded(true);
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshAgents();
  }, [refreshAgents]);

  const value = useMemo(
    () => ({ agents, agentsLoaded, setAgents, refreshAgents }),
    [agents, agentsLoaded, refreshAgents],
  );

  return <AgentsContext.Provider value={value}>{children}</AgentsContext.Provider>;
}

const disconnectedValue: AgentsContextValue = {
  agents: [],
  agentsLoaded: false,
  setAgents: noopSetAgents,
  refreshAgents: noopRefresh,
};

export function AgentsProvider({ children }: { children: ReactNode }) {
  const { connected, initialized } = useAuth();

  if (initialized && connected) {
    return <ConnectedAgentsProvider>{children}</ConnectedAgentsProvider>;
  }

  return <AgentsContext.Provider value={disconnectedValue}>{children}</AgentsContext.Provider>;
}

export function useAgents() {
  const context = useContext(AgentsContext);
  if (!context) {
    throw new Error("useAgents must be used within AgentsProvider");
  }
  return context;
}
