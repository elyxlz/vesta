import {
  createContext,
  useContext,
  useEffect,
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

export function AgentsProvider({ children }: { children: ReactNode }) {
  const { connected, initialized } = useAuth();
  const [agents, setAgents] = useState<ListEntry[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);

  const refreshAgents = async () => {
    if (!connected) {
      setAgents([]);
      setAgentsLoaded(true);
      return [];
    }

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
  };

  useEffect(() => {
    if (!initialized) return;

    if (!connected) {
      setAgents([]);
      setAgentsLoaded(true);
      return;
    }

    void refreshAgents();
  }, [initialized, connected, refreshAgents]);

  const value = {
    agents,
    agentsLoaded,
    setAgents,
    refreshAgents,
  };

  return <AgentsContext.Provider value={value}>{children}</AgentsContext.Provider>;
}

export function useAgents() {
  const context = useContext(AgentsContext);
  if (!context) {
    throw new Error("useAgents must be used within AgentsProvider");
  }
  return context;
}
