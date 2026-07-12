import { type Dispatch, type SetStateAction, useState } from "react";
import { type MotionValue } from "motion/react";
import { useLocation, useMatch, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
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
  const { name, agent, restart } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();
  const chatKeyboardFocused = useLayout((s) => s.chatKeyboardFocused);
  const restartPending = useRestartPending((s) =>
    Boolean(name && s.pending[name]?.reasons.length),
  );
  const [restarting, setRestarting] = useState(false);
  // Route through the provider's restart so clearing the pending flag has a single owner (the
  // provider), whichever surface triggers a restart. withOp resolves after completion (it handles
  // failure internally and keeps the flag set), so the spinner ends correctly either way.
  const applyRestart = async () => {
    if (!name) return;
    setRestarting(true);
    try {
      await restart();
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
  // Subpages go back to wherever they were opened from (chat or dashboard); a
  // deep link has no in-app history (location.key === "default"), so fall back
  // to the dashboard.
  const showBack = !!logsMatch || !!settingsMatch;
  const showDashboardBack = !isMobile && !!chatMatch;
  const goBack = () => {
    if (location.key === "default") {
      navigate(`/agent/${encodeURIComponent(name)}`);
    } else {
      navigate(-1);
    }
  };
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
          showBack ? (
            <LeadingButton label="back" icon={<ArrowLeft />} onClick={goBack} />
          ) : showDashboardBack ? (
            <LeadingButton
              label="dashboard"
              icon={<LayoutDashboard />}
              onClick={() => navigate(`/agent/${encodeURIComponent(name)}`)}
            />
          ) : (
            <LeadingButton
              label="home"
              icon={<Home />}
              onClick={() => navigate("/")}
            />
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
                    (restarting ? "restarting..." : "restart to apply")}
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

function LeadingButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="icon-lg"
          aria-label={label}
          onClick={onClick}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
