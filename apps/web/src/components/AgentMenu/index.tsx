import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { MoreVertical } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useModals } from "@/providers/ModalsProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useSwitchGateway } from "@/stores/use-switch-gateway";
import { AgentServicesList } from "@/components/AgentServices";
import type { MenuState } from "./types";
import { MobileMenu } from "./MobileMenu";
import { DesktopMenu } from "./DesktopMenu";
import { agentNeedsUser } from "@vesta/core";

export function AgentMenu() {
  const navigate = useNavigate();
  const location = useLocation();
  // Re-selecting the current page must not push a duplicate history entry:
  // the navbar's back button pops one entry per press, and a duplicate makes
  // the first press a visible no-op.
  const goTo = (path: string) => {
    if (location.pathname !== path) void navigate(path);
  };
  const { name, agent, isBusy, start, stop, restart } = useSelectedAgent();
  const { setDeleteDialogOpen, setBackupDialogOpen, handleOpenAuth } =
    useModals();
  const gateway = useGateway();
  const openSwitchGateway = useSwitchGateway((s) => s.setOpen);

  const [open, setOpen] = useState(false);
  const [servicesOpen, setServicesOpen] = useState(false);
  const isMobile = useIsMobile();

  const isRunning =
    agent.status !== "stopped" &&
    agent.status !== "dead" &&
    agent.status !== "not_found";

  const state: MenuState = {
    name,
    isRunning,
    showAliveActions: agent.status === "alive",
    isBusy,
    onToggle: () => {
      if (isRunning) stop();
      else start();
    },
    onLogs: () => goTo(`/agent/${encodeURIComponent(name)}/logs`),
    onServices: () => setServicesOpen(true),
    onAppSettings: () => {
      void navigate("/settings");
    },
    onAgentSettings: () => goTo(`/agent/${encodeURIComponent(name)}/settings`),
    onSwitchGateway: () => openSwitchGateway(true),
    onRestart: () => void restart(),
    onBackup: () => setBackupDialogOpen(true),
    onAuthenticate: gateway.reachable ? () => handleOpenAuth() : undefined,
    isAuthenticated: !agentNeedsUser(agent.status),
    onDelete: () => setDeleteDialogOpen(true),
  };

  const trigger = (
    <Button size="icon-lg" variant="outline" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  return (
    <>
      {isMobile ? (
        <MobileMenu
          state={state}
          open={open}
          onOpenChange={setOpen}
          trigger={trigger}
        />
      ) : (
        <DesktopMenu
          state={state}
          open={open}
          onOpenChange={setOpen}
          trigger={trigger}
        />
      )}
      <Dialog open={servicesOpen} onOpenChange={setServicesOpen}>
        <DialogContent className="max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>services</DialogTitle>
          </DialogHeader>
          <AgentServicesList />
        </DialogContent>
      </Dialog>
    </>
  );
}
