import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { Navigate, Outlet, useMatch, useNavigate, useParams } from "react-router-dom";
import { KeyRound, LayoutDashboard, MessageSquare } from "lucide-react";
import { AgentIsland } from "@/components/AgentIsland";
import { UpdateBar } from "@/components/UpdateBar";
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
  const isMobile = useIsMobile();
  const [chatCollapsed, setChatCollapsed] = useState(isMobile);

  useEffect(() => {
    setChatCollapsed(isMobile);
  }, [isMobile]);

  return (
    <VoiceProvider>
      <ChatProvider>
        <ModalsProvider>
          <div className="flex-1 min-h-0 flex flex-col relative">
            <div className="absolute inset-x-0 top-0 z-10">
              <AgentNavbar chatCollapsed={chatCollapsed} setChatCollapsed={setChatCollapsed} />
            </div>
            <div className="flex-1 min-h-0 flex flex-col">
              <Outlet context={{ chatCollapsed, setChatCollapsed }} />
            </div>
          </div>
          <AgentIslandModals />
        </ModalsProvider>
      </ChatProvider>
    </VoiceProvider>
  );
}

function AgentNavbar({
  chatCollapsed,
  setChatCollapsed,
}: {
  chatCollapsed: boolean;
  setChatCollapsed: Dispatch<SetStateAction<boolean>>;
}) {
  const navigate = useNavigate();
  const { connected } = useAuth();
  const { name, agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const isMobile = useIsMobile();
  const showMobileReauth = isMobile && agent?.status === "running" && !agent?.authenticated;
  const agentDashboardMatch = useMatch({ path: "/agent/:name", end: true });
  const agentChatMatch = useMatch({ path: "/agent/:name/chat", end: true });
  const agentLogsMatch = useMatch({ path: "/agent/:name/logs", end: true });
  const showChatButton =
    connected &&
    agentDashboardMatch &&
    name.length > 0 &&
    (isMobile || chatCollapsed);
  const showDashButton =
    connected && (agentChatMatch || agentLogsMatch) && name.length > 0;

  return (
    <div className="shrink-0 px-page">
      <Navbar
        center={
          <>
            <AgentIsland />
            <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 flex flex-col items-center gap-2">
              {showMobileReauth && (
                <Button size="sm" onClick={() => void handleOpenAuth()}>
                  <KeyRound data-icon="inline-start" />
                  reauthenticate
                </Button>
              )}
              <UpdateBar />
            </div>
          </>
        }
        trailing={
          connected ? (
            <div className="flex items-center gap-2">
              {showDashButton && (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-muted-foreground"
                  onClick={() => navigate(`/agent/${encodeURIComponent(name)}`)}
                >
                  <LayoutDashboard data-icon="inline-start" />
                  dash
                </Button>
              )}
              {showChatButton && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (isMobile) {
                      navigate(`/agent/${encodeURIComponent(name)}/chat`);
                    } else {
                      setChatCollapsed(false);
                    }
                  }}
                >
                  <MessageSquare data-icon="inline-start" />
                  chat
                </Button>
              )}
              <div data-agent-menu className="flex items-center">
                <AgentMenu />
              </div>
            </div>
          ) : undefined
        }
      />
    </div>
  );
}
