import { createContext, useContext } from "react";
import { Navigate, Outlet, useParams } from "react-router-dom";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { useAgentIsland } from "@/hooks/use-agent-island";
import { useAgents } from "@/providers/AgentsProvider";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";

type AgentIslandValue = ReturnType<typeof useAgentIsland>;

const AgentIslandContext = createContext<AgentIslandValue | null>(null);

export function useAgentIslandContext() {
  const value = useContext(AgentIslandContext);
  if (!value) {
    throw new Error("useAgentIslandContext must be used within AgentLayout");
  }
  return value;
}

function AgentLayoutInner() {
  const island = useAgentIsland({ menuAnchoredInNavbar: true });

  return (
    <AgentIslandContext.Provider value={island}>
      <Outlet />
      <AgentIslandModals {...island} />
    </AgentIslandContext.Provider>
  );
}

export function AgentLayout() {
  const { name } = useParams<{ name: string }>();
  const { agents } = useAgents();

  if (!agents.some((a) => a.name === name)) {
    return <Navigate to="/" replace />;
  }

  return (
    <SelectedAgentProvider>
      <AgentLayoutInner />
    </SelectedAgentProvider>
  );
}
