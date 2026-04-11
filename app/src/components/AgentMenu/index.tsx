import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MoreVertical, SlidersHorizontal } from "lucide-react";
import { SettingsDialog } from "@/components/Settings";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useChatContext } from "@/providers/ChatProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import type { MenuState } from "./types";
import { MobileMenu } from "./MobileMenu";
import { DesktopMenu } from "./DesktopMenu";

export function AgentMenu() {
  const navigate = useNavigate();
  const { name, agent, isBusy, start, stop, restart, rebuild, backup } =
    useSelectedAgent();
  const { setDeleteDialogOpen } = useModals();
  const { showToolCalls, setShowToolCalls } = useChatContext();

  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const isMobile = useIsMobile();

  const isRunning = agent?.status === "running";

  const state: MenuState = {
    name,
    isRunning,
    showAliveActions: agent?.alive,
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
  };

  const trigger = (
    <Button size="icon-lg" variant="outline" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  if (isMobile) {
    return (
      <>
        <MobileMenu
          state={state}
          open={open}
          onOpenChange={setOpen}
          trigger={trigger}
        />
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} agentSettingsSlot={
          <Button variant="default" className="w-full justify-start" onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}>
            <SlidersHorizontal data-icon="inline-start" />
            {name}'s settings
          </Button>
        } />
      </>
    );
  }

  return (
    <>
      <DesktopMenu
        state={state}
        open={open}
        onOpenChange={setOpen}
        trigger={trigger}
      />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} agentSettingsSlot={
        <Button variant="default" className="w-full justify-start" onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}>
          <SlidersHorizontal data-icon="inline-start" />
          {name}'s settings
        </Button>
      } />
    </>
  );
}
