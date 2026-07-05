import { type Dispatch, type SetStateAction, useState } from "react";
import { type MotionValue } from "motion/react";
import { useMatch, useNavigate } from "react-router-dom";
import {
  Home,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  RotateCw,
} from "lucide-react";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { MobileNavbar } from "@/components/MobileNavbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAuth } from "@/providers/AuthProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useLayout } from "@/stores/use-layout";
import { useRestartPending } from "@/stores/use-restart-pending";
import { restartAgent } from "@/api/agents";
import { Navbar } from "..";

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
  const { reachable } = useGateway();
  const { name, agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const chatKeyboardFocused = useLayout((s) => s.chatKeyboardFocused);
  const restartPending = useRestartPending((s) =>
    name ? (s.pending[name] ?? false) : false,
  );
  const clearRestartPending = useRestartPending((s) => s.clearPending);
  const [restarting, setRestarting] = useState(false);
  const applyRestart = async () => {
    if (!name) return;
    setRestarting(true);
    try {
      await restartAgent(name);
      clearRestartPending(name);
    } catch {
      // Leave the flag set so the user can retry.
    } finally {
      setRestarting(false);
    }
  };
  const needsAuth =
    (agent?.status === "not_authenticated" ||
      agent?.status === "unprovisioned") &&
    reachable;

  const agentDashboardMatch = useMatch({ path: "/agent/:name", end: true });
  const chatMatch = useMatch({ path: "/agent/:name/chat", end: true });
  const logsMatch = useMatch({ path: "/agent/:name/logs", end: true });
  const settingsMatch = useMatch({ path: "/agent/:name/settings", end: true });

  const showMobileNavbar = isMobile && (!!agentDashboardMatch || !!chatMatch);
  const hideMobileNavbar = isMobile && !!chatMatch && chatKeyboardFocused;
  const showDashboardBack = isMobile
    ? !!logsMatch || !!settingsMatch
    : !!chatMatch || !!logsMatch || !!settingsMatch;
  const showChatButton =
    connected &&
    agentDashboardMatch &&
    name.length > 0 &&
    !isMobile &&
    chatCollapsed;

  return (
    <>
      <Navbar
        leading={
          showDashboardBack ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-lg"
                  aria-label="dashboard"
                  onClick={() => navigate(`/agent/${encodeURIComponent(name)}`)}
                >
                  <LayoutDashboard />
                </Button>
              </TooltipTrigger>
              <TooltipContent>dashboard</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-lg"
                  aria-label="home"
                  onClick={() => navigate("/")}
                >
                  <Home />
                </Button>
              </TooltipTrigger>
              <TooltipContent>home</TooltipContent>
            </Tooltip>
          )
        }
        center={<AgentIsland />}
        trailing={
          connected ? (
            <div className="flex items-center gap-2">
              <StatusPill showHostname={false} />
              {restartPending && (
                <Button
                  variant="default"
                  size={isMobile ? "icon-lg" : "lg"}
                  disabled={restarting}
                  aria-label="restart to apply changes"
                  onClick={() => void applyRestart()}
                >
                  <RotateCw
                    data-icon={isMobile ? undefined : "inline-start"}
                    className={restarting ? "animate-spin" : undefined}
                  />
                  {!isMobile &&
                    (restarting ? "restarting…" : "restart to apply")}
                </Button>
              )}
              {!isMobile && needsAuth && (
                <Button
                  variant="default"
                  size="lg"
                  onClick={() => void handleOpenAuth()}
                >
                  <KeyRound data-icon="inline-start" />
                  sign in
                </Button>
              )}
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
      {showMobileNavbar && !hideMobileNavbar && (
        <MobileNavbar progress={swipeProgress} />
      )}
    </>
  );
}
