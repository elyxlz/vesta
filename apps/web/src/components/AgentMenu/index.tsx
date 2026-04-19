import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MoreVertical, SlidersHorizontal } from "lucide-react";
import { SettingsDialog } from "@/components/Settings";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useChatContext } from "@/providers/ChatProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { apiJson } from "@/api/client";
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
  const [treeLines, setTreeLines] = useState<string[] | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const isMobile = useIsMobile();

  const fetchTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const data = await apiJson<{ tree: string[] }>(
        `/agents/${encodeURIComponent(name)}/tree`,
      );
      setTreeLines(data.tree);
    } catch {
      setTreeLines(null);
    } finally {
      setTreeLoading(false);
    }
  }, [name]);

  const isRunning =
    agent?.status !== "stopped" &&
    agent?.status !== "dead" &&
    agent?.status !== "not_found";

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
    onDebugInfo: () => setDebugOpen(true),
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

  const agentSettingsSlot = (
    <Button
      variant="default"
      className="w-full justify-start"
      onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}
    >
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
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        agentSettingsSlot={agentSettingsSlot}
      />
      <Dialog open={debugOpen} onOpenChange={setDebugOpen}>
        <DialogContent
          className="max-w-lg max-h-[80vh] overflow-auto"
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle>debug info</DialogTitle>
          </DialogHeader>
          <Tabs defaultValue="socket">
            <TabsList>
              <TabsTrigger value="socket">control socket</TabsTrigger>
              <TabsTrigger
                value="tree"
                onClick={() => {
                  if (!treeLines && !treeLoading) fetchTree();
                }}
              >
                file tree
              </TabsTrigger>
            </TabsList>
            <TabsContent value="socket">
              <p className="text-xs text-muted-foreground mb-2">
                last updated: {lastUpdated}
              </p>
              <pre className="text-xs whitespace-pre-wrap break-all">
                {debugJson}
              </pre>
            </TabsContent>
            <TabsContent value="tree">
              {treeLoading ? (
                <p className="text-xs text-muted-foreground">loading...</p>
              ) : treeLines ? (
                <pre className="text-xs whitespace-pre-wrap break-all">
                  {treeLines.join("\n")}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">
                  agent must be running to view file tree
                </p>
              )}
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
    </>
  );
}
