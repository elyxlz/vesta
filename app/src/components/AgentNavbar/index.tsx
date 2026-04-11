import { type Dispatch, type SetStateAction } from "react";
import { useMatch, useNavigate } from "react-router-dom";
import { KeyRound, LayoutDashboard, MessageSquare } from "lucide-react";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { ConnectedNavbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAuth } from "@/providers/AuthProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function AgentNavbar({
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
  const showMobileReauth =
    isMobile && agent?.status === "running" && !agent?.authenticated;
  const agentDashboardMatch = useMatch({ path: "/agent/:name", end: true });
  const agentChatMatch = useMatch({ path: "/agent/:name/chat", end: true });
  const agentLogsMatch = useMatch({ path: "/agent/:name/logs", end: true });
  const agentSettingsMatch = useMatch({
    path: "/agent/:name/settings",
    end: true,
  });
  const showChatButton =
    connected &&
    agentDashboardMatch &&
    name.length > 0 &&
    (isMobile || chatCollapsed);
  const showDashButton =
    connected &&
    (agentChatMatch || agentLogsMatch || agentSettingsMatch) &&
    name.length > 0;

  return (
    <ConnectedNavbar
      leadingExtra={
        showDashButton ? (
          <Button
            variant={"default"}
            size={isMobile ? "icon-lg" : "lg"}
            aria-label={isMobile ? "Dashboard" : undefined}
            onClick={() => navigate(`/agent/${encodeURIComponent(name)}`)}
          >
            <LayoutDashboard
              {...(isMobile ? {} : { "data-icon": "inline-start" as const })}
            />
            {!isMobile && "dashboard"}
          </Button>
        ) : undefined
      }
      center={
        <>
          <AgentIsland />
          {showMobileReauth && (
            <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 flex flex-col items-center gap-2">
              <Button
                variant="default"
                size="lg"
                onClick={() => void handleOpenAuth()}
              >
                <KeyRound data-icon="inline-start" />
                reauthenticate
              </Button>
            </div>
          )}
        </>
      }
      trailing={
        connected ? (
          <div className="flex items-center gap-2">
            <StatusPill showHostname={false} />
            {showChatButton && (
              <Button
                variant="default"
                size={isMobile ? "icon-lg" : "lg"}
                aria-label={isMobile ? "Chat" : undefined}
                onClick={() => {
                  if (isMobile) {
                    navigate(`/agent/${encodeURIComponent(name)}/chat`);
                  } else {
                    setChatCollapsed(false);
                  }
                }}
              >
                <MessageSquare
                  {...(isMobile ? {} : { "data-icon": "inline-start" as const })}
                />
                {!isMobile && "chat"}
              </Button>
            )}
            <div data-agent-menu className="flex items-center">
              <AgentMenu />
            </div>
          </div>
        ) : undefined
      }
    />
  );
}
