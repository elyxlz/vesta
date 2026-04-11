import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MoreVertical, SlidersHorizontal } from "lucide-react";
import { SettingsDialog } from "@/components/Settings";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useChatContext } from "@/providers/ChatProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useGateway } from "@/providers/GatewayProvider";
import type { MenuState } from "./types";
import { MobileMenu } from "./MobileMenu";
import { DesktopMenu } from "./DesktopMenu";

export function AgentMenu() {
  const navigate = useNavigate();
  const { name, agent, isBusy, start, stop, restart, rebuild, backup } =
    useSelectedAgent();
  const { setDeleteDialogOpen } = useModals();
  const { showToolCalls, setShowToolCalls } = useChatContext();
  const gateway = useGateway();

  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const isMobile = useIsMobile();

  const isRunning = agent?.status !== "stopped" && agent?.status !== "dead" && agent?.status !== "not_found";

  const state: MenuState = {
    name,
    isRunning,
    showAliveActions: agent?.status === "alive",
    isBusy,
    showToolCalls,
    onToggle: () => void (isRunning ? stop() : start()),
    onLogs: () => navigate(`/agent/${encodeURIComponent(name)}/logs`),
    onToolCalls: () => setShowToolCalls((v) => !v),
    onOpenSettings: () => setSettingsOpen(true),
    onRestart: () => void restart(),
    onRebuild: () => void rebuild(),
    onBackup: () => void backup(),
    onDelete: () => setDeleteDialogOpen(true),
    ...(import.meta.env.DEV && { onDebugInfo: () => setDebugOpen(true) }),
  };

  const trigger = (
    <Button size="icon-lg" variant="outline" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  const debugJson = JSON.stringify({ gateway: { reachable: gateway.reachable, version: gateway.gatewayVersion, port: gateway.gatewayPort }, agents: gateway.agents }, null, 2);
  const lastUpdatedRef = useRef(new Date().toLocaleTimeString());
  const prevJsonRef = useRef(debugJson);
  if (debugJson !== prevJsonRef.current) {
    prevJsonRef.current = debugJson;
    lastUpdatedRef.current = new Date().toLocaleTimeString();
  }

  const agentSettingsSlot = (
    <Button variant="default" className="w-full justify-start" onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}>
      <SlidersHorizontal data-icon="inline-start" />
      {name}'s settings
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
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} agentSettingsSlot={agentSettingsSlot} />
      {import.meta.env.DEV && (
        <Dialog open={debugOpen} onOpenChange={setDebugOpen}>
          <DialogContent className="max-w-lg max-h-[80vh] overflow-auto">
            <DialogHeader>
              <DialogTitle>control socket</DialogTitle>
              <p className="text-xs text-muted-foreground">last updated: {lastUpdatedRef.current}</p>
            </DialogHeader>
            <pre className="text-xs whitespace-pre-wrap break-all">
              {debugJson}
            </pre>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
