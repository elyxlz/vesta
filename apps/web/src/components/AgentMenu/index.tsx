import { useEffect, useRef, useState } from "react";
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
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { useAppMode } from "@/stores/use-app-mode";
import type { MenuState } from "./types";
import { MobileMenu } from "./MobileMenu";
import { DesktopMenu } from "./DesktopMenu";

export function AgentMenu() {
  const navigate = useNavigate();
  const location = useLocation();
  // Re-selecting the current page must not push a duplicate history entry:
  // the navbar's back button pops one entry per press, and a duplicate makes
  // the first press a visible no-op.
  const goTo = (path: string) => {
    if (location.pathname !== path) void navigate(path);
  };
  const { name, agent, isBusy, start, stop, restart, backup } =
    useSelectedAgent();
  const { setDeleteDialogOpen, handleOpenAuth } = useModals();
  const gateway = useGateway();
  const appMode = useAppMode((s) => s.mode);

  const [open, setOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
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
    onAppSettings: () => {
      void navigate("/settings");
    },
    onAgentSettings: () => goTo(`/agent/${encodeURIComponent(name)}/settings`),
    onRestart: () => void restart(),
    onBackup: () => backup(),
    onAuthenticate: gateway.reachable ? () => handleOpenAuth() : undefined,
    isAuthenticated:
      agent.status !== "not_authenticated" && agent.status !== "unprovisioned",
    onDelete: () => setDeleteDialogOpen(true),
    onDebugInfo: appMode === "advanced" ? () => setDebugOpen(true) : undefined,
  };

  const trigger = (
    <Button size="icon-lg" variant="outline" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  const debugJson = JSON.stringify(
    {
      gateway: {
        reachable: gateway.reachable,
        version: gateway.gatewayVersion,
        port: gateway.gatewayPort,
      },
      agents: gateway.agents,
    },
    null,
    2,
  );
  const [lastUpdated, setLastUpdated] = useState(() =>
    new Date().toLocaleTimeString(),
  );
  const prevJsonRef = useRef(debugJson);
  useEffect(() => {
    if (debugJson !== prevJsonRef.current) {
      prevJsonRef.current = debugJson;
      setLastUpdated(new Date().toLocaleTimeString());
    }
  }, [debugJson]);

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
      <Dialog open={debugOpen} onOpenChange={setDebugOpen}>
        <DialogContent
          className="max-w-lg max-h-[80vh] overflow-auto"
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle>debug info</DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground mb-2">
            last updated: {lastUpdated}
          </p>
          <pre className="text-xs whitespace-pre-wrap break-all">
            {debugJson}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
