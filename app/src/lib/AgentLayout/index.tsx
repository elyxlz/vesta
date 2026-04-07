import { Navigate, Outlet, useParams } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { AgentMenu } from "@/components/AgentMenu";
import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAgents } from "@/providers/AgentsProvider";
import { useAuth } from "@/providers/AuthProvider";
import { ChatProvider } from "@/providers/ChatProvider";
import { ModalsProvider, useModals } from "@/providers/ModalsProvider";
import { SelectedAgentProvider, useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { VoiceProvider } from "@/providers/VoiceProvider";

export function AgentLayout() {
  const { name: routeName } = useParams<{ name: string }>();
  const { agents } = useAgents();

  if (!agents.some((a) => a.name === routeName)) {
    return <Navigate to="/home" replace />;
  }

  return (
    <SelectedAgentProvider>
      <AgentLayoutInner />
    </SelectedAgentProvider>
  );
}

function AgentLayoutInner() {
  return (
    <VoiceProvider>
      <ChatProvider>
        <ModalsProvider>
          <AgentNavbar />
          <div className="flex-1 min-h-0 flex flex-col">
            <Outlet />
          </div>
          <AgentIslandModals />
        </ModalsProvider>
      </ChatProvider>
    </VoiceProvider>
  );
}

function AgentNavbar() {
  const { connected } = useAuth();
  const { agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const isMobile = useIsMobile();
  const showMobileReauth = isMobile && agent?.status === "running" && !agent?.authenticated;

  return (
    <div className="shrink-0 px-3 sm:px-5">
      <Navbar
        center={
          <>
            <AgentIsland />
            {showMobileReauth && (
              <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2">
                <Button size="sm" onClick={() => void handleOpenAuth()}>
                  <KeyRound data-icon="inline-start" />
                  reauthenticate
                </Button>
              </div>
            )}
          </>
        }
        trailing={
          connected ? (
            <div data-agent-menu className="flex items-center">
              <AgentMenu />
            </div>
          ) : undefined
        }
      />
    </div>
  );
}
