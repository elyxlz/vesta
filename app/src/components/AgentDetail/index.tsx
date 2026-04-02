import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  MoreVertical,
  Play,
  Square,
  MessageCircle,
  KeyRound,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Orb } from "@/components/Orb";
import { AuthFlow } from "@/components/AuthFlow";
import {
  agentStatus,
  startAgent,
  stopAgent,
  restartAgent,
  rebuildAgent,
  backupAgent,
  restoreAgent,
  deleteAgent,
} from "@/lib/api";
import type { AgentInfo, AgentActivityState } from "@/lib/types";
import { useAppStore } from "@/stores/use-app-store";
import { useAgentOps } from "@/stores/use-agent-ops";
import { getOrbVisualState } from "@/components/Orb/styles";
import { useAgentWs } from "@/hooks/use-agent-ws";
import { cn } from "@/lib/utils";

export function AgentDetail() {
  const selectedAgent = useAppStore((s) => s.selectedAgent);
  const view = useAppStore((s) => s.view);
  const navigateHome = useAppStore((s) => s.navigateHome);
  const navigateToChat = useAppStore((s) => s.navigateToChat);
  const navigateToConsole = useAppStore((s) => s.navigateToConsole);
  const version = useAppStore((s) => s.version);

  const withOp = useAgentOps((s) => s.withOp);
  const getOp = useAgentOps((s) => s.getOp);
  const busyAgentName = useAgentOps((s) => s.busyAgentName);
  const removeAgent = useAgentOps((s) => s.removeAgent);

  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [hovered, setHovered] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const name = selectedAgent ?? "";
  const opState = getOp(name);
  const isBusy = busyAgentName() !== null;

  const { agentState } = useAgentWs(
    name,
    view !== "agent-chat" && agent?.alive === true,
  );

  useEffect(() => {
    if (!name) return;
    const fetchStatus = async () => {
      if (opState.operation !== "idle") return;
      try {
        const info = await agentStatus(name);
        setAgent(info);
      } catch {
        // ignore
      }
    };
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [name, opState.operation]);

  const orbState = agent
    ? getOrbVisualState(
        agent.status,
        agent.authenticated,
        agent.agent_ready,
        agentState,
        opState.operation,
      )
    : "dead";

  const statusLabel = getStatusLabel(agent, opState.operation, opState.error);

  const handleStart = useCallback(() => {
    withOp(name, "starting", () => startAgent(name), "start failed");
  }, [name, withOp]);

  const handleStop = useCallback(() => {
    withOp(name, "stopping", () => stopAgent(name), "stop failed");
  }, [name, withOp]);

  const handleRestart = useCallback(() => {
    withOp(name, "starting", () => restartAgent(name), "restart failed");
  }, [name, withOp]);

  const handleRebuild = useCallback(() => {
    withOp(name, "rebuilding", () => rebuildAgent(name), "rebuild failed");
  }, [name, withOp]);

  const handleBackup = useCallback(() => {
    withOp(name, "backing-up", () => backupAgent(name), "backup failed");
  }, [name, withOp]);

  const handleRestore = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".tar.gz,.gz";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      await withOp(
        name,
        "restoring",
        () => restoreAgent(file, name, true),
        "restore failed",
      );
    };
    input.click();
  }, [name, withOp]);

  const handleDelete = useCallback(async () => {
    await withOp(name, "deleting", () => deleteAgent(name), "delete failed");
    removeAgent(name);
    navigateHome();
  }, [name, withOp, removeAgent, navigateHome]);

  const showButtons = hovered || !agent?.alive || opState.operation !== "idle";

  return (
    <div
      className="flex flex-col h-full animate-view-in"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="px-3 pt-1">
        <button
          onClick={navigateHome}
          className="flex items-center gap-1 text-[12px] text-muted hover:text-foreground transition-colors"
        >
          <ArrowLeft size={14} />
          back
        </button>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <Orb state={orbState} size={140} enableTracking />

        <div className="text-center">
          <p className="text-[16px] font-semibold">{name}</p>
          <p
            className={cn(
              "text-[11px] mt-0.5",
              opState.error ? "text-destructive animate-shake" : "text-muted",
            )}
          >
            {statusLabel}
          </p>
        </div>

        {showAuth && agent?.status === "running" && (
          <AuthFlow
            agentName={name}
            onCancel={() => setShowAuth(false)}
            onComplete={() => setShowAuth(false)}
          />
        )}

        {opState.operation === "idle" && !showAuth && (
          <div
            className={cn(
              "flex items-center gap-2 transition-opacity",
              showButtons ? "opacity-100" : "opacity-0",
            )}
          >
            {confirmDelete ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={handleDelete}
                    >
                      <Trash2 size={14} className="mr-1" />
                      confirm
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>permanently delete</TooltipContent>
                </Tooltip>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmDelete(false)}
                  className="text-muted"
                >
                  <X size={14} className="mr-1" />
                  cancel
                </Button>
              </>
            ) : (
              <>
                {agent?.alive && (
                  <Button
                    size="sm"
                    onClick={() => navigateToChat(name)}
                  >
                    <MessageCircle size={14} className="mr-1" />
                    chat
                  </Button>
                )}
                {agent?.status === "running" && !agent.authenticated && (
                  <Button
                    size="sm"
                    onClick={() => setShowAuth(true)}
                  >
                    <KeyRound size={14} className="mr-1" />
                    authenticate
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isBusy}
                  onClick={
                    agent?.status === "running" ? handleStop : handleStart
                  }
                >
                  {agent?.status === "running" ? (
                    <>
                      <Square size={14} className="mr-1" />
                      stop
                    </>
                  ) : (
                    <>
                      <Play size={14} className="mr-1" />
                      start
                    </>
                  )}
                </Button>

                <DropdownMenu
                  onOpenChange={(open) => {
                    if (!open) setConfirmDelete(false);
                  }}
                >
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="ghost" className="px-2">
                      <MoreVertical size={14} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="center"
                    side="top"
                    className="animate-menu-in min-w-[150px]"
                  >
                    {agent?.alive && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <DropdownMenuItem
                            className="text-[12px]"
                            onClick={() => navigateToConsole(name)}
                          >
                            console
                          </DropdownMenuItem>
                        </TooltipTrigger>
                        <TooltipContent side="left">
                          view raw logs
                        </TooltipContent>
                      </Tooltip>
                    )}
                    {agent?.status === "running" && (
                      <>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <DropdownMenuItem
                              className="text-[12px]"
                              disabled={isBusy}
                              onClick={handleRestart}
                            >
                              restart
                            </DropdownMenuItem>
                          </TooltipTrigger>
                          <TooltipContent side="left">
                            restart agent
                          </TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <DropdownMenuItem
                              className="text-[12px]"
                              disabled={isBusy}
                              onClick={handleRebuild}
                            >
                              rebuild
                            </DropdownMenuItem>
                          </TooltipTrigger>
                          <TooltipContent side="left">
                            rebuild container from latest image
                          </TooltipContent>
                        </Tooltip>
                        {agent.authenticated && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <DropdownMenuItem
                                className="text-[12px]"
                                onClick={() => setShowAuth(true)}
                              >
                                authenticate
                              </DropdownMenuItem>
                            </TooltipTrigger>
                            <TooltipContent side="left">
                              authenticate claude
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </>
                    )}
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <DropdownMenuItem
                          className="text-[12px]"
                          disabled={isBusy}
                          onClick={handleBackup}
                        >
                          backup
                        </DropdownMenuItem>
                      </TooltipTrigger>
                      <TooltipContent side="left">
                        export to file
                      </TooltipContent>
                    </Tooltip>
                    <DropdownMenuItem
                      className="text-[12px]"
                      disabled={isBusy}
                      onClick={handleRestore}
                    >
                      load backup
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <DropdownMenuItem
                          className="text-destructive text-[12px]"
                          disabled={isBusy}
                          onClick={() => setConfirmDelete(true)}
                        >
                          delete
                        </DropdownMenuItem>
                      </TooltipTrigger>
                      <TooltipContent side="left">
                        permanently delete
                      </TooltipContent>
                    </Tooltip>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
          </div>
        )}
      </div>

      {version && (
        <div className="text-center pb-3">
          <span className="text-[10px] text-muted">v{version}</span>
        </div>
      )}
    </div>
  );
}

function getStatusLabel(
  agent: AgentInfo | null,
  operation: string,
  error: string,
): string {
  if (error) return error;

  switch (operation) {
    case "stopping":
      return "stopping...";
    case "starting":
      return "starting...";
    case "authenticating":
      return "signing in...";
    case "deleting":
      return "deleting...";
    case "rebuilding":
      return "rebuilding...";
    case "backing-up":
      return "backing up...";
    case "restoring":
      return "restoring...";
  }

  if (!agent) return "";

  if (agent.alive) return "alive";
  if (agent.status === "running" && agent.authenticated && !agent.agent_ready)
    return "waking up...";
  if (agent.status === "running" && !agent.authenticated) return "not signed in";
  if (agent.status === "stopped") return "stopped";
  if (agent.status === "dead") return "broken — delete and recreate";
  return agent.friendly_status || agent.status;
}
