import { createContext, useContext } from "react";
import { Navigate, Outlet, useParams } from "react-router-dom";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { useAgentIsland } from "@/hooks/use-agent-island";
import { useAgents } from "@/providers/AgentsProvider";
import { SelectedAgentProvider, useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { VoiceProvider } from "@/providers/VoiceProvider";

type AgentIslandValue = ReturnType<typeof useAgentIsland>;

const AgentIslandContext = createContext<AgentIslandValue | null>(null);

export function useAgentIslandContext() {
  const value = useContext(AgentIslandContext);
  if (!value) {
    throw new Error("useAgentIslandContext must be used within AgentLayout");
  }
  return value;
}

function AgentLayoutWithVoice() {
  const { name } = useSelectedAgent();
  const island = useAgentIsland({ menuAnchoredInNavbar: true });

  return (
    <VoiceProvider agentName={name}>
      <AgentIslandContext.Provider value={island}>
        <Outlet />
        <AgentIslandModals {...island} />
      </AgentIslandContext.Provider>
    </VoiceProvider>
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
      <AgentLayoutWithVoice />
    </SelectedAgentProvider>
  );
}
