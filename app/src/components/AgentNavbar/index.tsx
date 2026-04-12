import { type Dispatch, type SetStateAction } from "react";
import { type MotionValue } from "motion/react";
import { useMatch, useNavigate } from "react-router-dom";
import { KeyRound, LayoutDashboard, MessageSquare } from "lucide-react";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { BottomTabs } from "@/components/BottomTabs";
import { ConnectedNavbar, NavbarLeading } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAuth } from "@/providers/AuthProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function AgentNavbar({
  chatCollapsed,
  setChatCollapsed,
  swipeProgress,
}: {
  chatCollapsed: boolean;
  setChatCollapsed: Dispatch<SetStateAction<boolean>>;
  swipeProgress: MotionValue<number>;
}) {
  const { connected } = useAuth();
  const { name, agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const showMobileReauth =
    isMobile && agent?.status === "not_authenticated";
  const agentDashboardMatch = useMatch({ path: "/agent/:name", end: true });
  const chatMatch = useMatch({ path: "/agent/:name/chat", end: true });
  const logsMatch = useMatch({ path: "/agent/:name/logs", end: true });
  const showBottomTabs = isMobile && (!!agentDashboardMatch || !!chatMatch);
  const isSubpage = !isMobile && (!!chatMatch || !!logsMatch);
  const showChatButton =
    connected &&
    agentDashboardMatch &&
    name.length > 0 &&
    !isMobile &&
    chatCollapsed;
  return (
    <>
      <ConnectedNavbar
        leading={
          isSubpage ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-lg"
                  onClick={() => navigate(`/agent/${encodeURIComponent(name)}`)}
                >
                  <LayoutDashboard />
                </Button>
              </TooltipTrigger>
              <TooltipContent>dashboard</TooltipContent>
            </Tooltip>
          ) : (
            <NavbarLeading />
          )
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
                  size="lg"
                  onClick={() => setChatCollapsed(false)}
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
      {showBottomTabs && <BottomTabs progress={swipeProgress} />}
    </>
  );
}
