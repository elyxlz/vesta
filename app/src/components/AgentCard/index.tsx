import { useCallback, useState } from "react";
import { MoreVertical } from "lucide-react";
import { Orb } from "@/components/Orb";
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
import type { ListEntry, AgentActivityState } from "@/lib/types";
import {
  startAgent,
  stopAgent,
  restartAgent,
  backupAgent,
  restoreAgent,
  deleteAgent,
} from "@/api";
import { useNavigation } from "@/stores/use-navigation";
import { useAgentOps } from "@/stores/use-agent-ops";
import { getOrbVisualState } from "@/components/Orb/styles";

interface AgentCardProps {
  agent: ListEntry;
  activityState: AgentActivityState;
}

export function AgentCard({ agent, activityState }: AgentCardProps) {
  const navigateToAgent = useNavigation((s) => s.navigateToAgent);
  const navigateToChat = useNavigation((s) => s.navigateToChat);
  const navigateToConsole = useNavigation((s) => s.navigateToConsole);
  const withOp = useAgentOps((s) => s.withOp);
  const busyAgentName = useAgentOps((s) => s.busyAgentName);
  const getOp = useAgentOps((s) => s.getOp);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const opState = getOp(agent.name);
  const isBusy = busyAgentName() !== null;
  const orbState = getOrbVisualState(
    agent.status,
    agent.authenticated,
    agent.agent_ready,
    activityState,
    opState.operation,
  );

  const handleClick = useCallback(() => {
    navigateToAgent(agent.name);
  }, [navigateToAgent, agent.name]);

  const handleFileRestore = useCallback(async () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".tar.gz,.gz";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      await withOp(
        agent.name,
        "restoring",
        () => restoreAgent(file, agent.name, true),
        "restore failed",
      );
    };
    input.click();
  }, [agent.name, withOp]);

  return (
    <div className="relative group flex flex-col items-center gap-2 p-4 cursor-pointer">
      <div onClick={handleClick}>
        <Orb state={orbState} size={56} />
      </div>
      <span
        className="text-sm font-medium text-foreground cursor-pointer"
        onClick={handleClick}
      >
        {agent.name}
      </span>

      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu
          onOpenChange={(open) => {
            if (!open) setConfirmDelete(false);
          }}
        >
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-xs">
              <MoreVertical size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="animate-menu-in min-w-[140px]">
            {confirmDelete ? (
              <>
                <DropdownMenuItem
                  className="text-destructive text-sm"
                  disabled={isBusy}
                  onClick={() =>
                    withOp(
                      agent.name,
                      "deleting",
                      () => deleteAgent(agent.name),
                      "delete failed",
                    )
                  }
                >
                  confirm delete
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-foreground/60 text-sm"
                  onClick={() => setConfirmDelete(false)}
                >
                  cancel
                </DropdownMenuItem>
              </>
            ) : (
              <>
                {agent.alive && (
                  <>
                    <DropdownMenuItem
                      className="text-sm"
                      onClick={() => navigateToChat(agent.name)}
                    >
                      chat
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-sm"
                      onClick={() => navigateToConsole(agent.name)}
                    >
                      console
                    </DropdownMenuItem>
                  </>
                )}
                <DropdownMenuItem
                  className="text-sm"
                  disabled={isBusy}
                  onClick={() => {
                    if (agent.status === "running") {
                      withOp(agent.name, "stopping", () => stopAgent(agent.name), "stop failed");
                    } else {
                      withOp(agent.name, "starting", () => startAgent(agent.name), "start failed");
                    }
                  }}
                >
                  {agent.status === "running" ? "stop" : "start"}
                </DropdownMenuItem>
                {agent.status === "running" && (
                  <DropdownMenuItem
                    className="text-sm"
                    disabled={isBusy}
                    onClick={() =>
                      withOp(agent.name, "starting", () => restartAgent(agent.name), "restart failed")
                    }
                  >
                    restart
                  </DropdownMenuItem>
                )}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuItem
                      className="text-sm"
                      disabled={isBusy}
                      onClick={() =>
                        withOp(agent.name, "backing-up", () => backupAgent(agent.name), "backup failed")
                      }
                    >
                      backup
                    </DropdownMenuItem>
                  </TooltipTrigger>
                  <TooltipContent>export to file</TooltipContent>
                </Tooltip>
                <DropdownMenuItem
                  className="text-sm"
                  disabled={isBusy}
                  onClick={handleFileRestore}
                >
                  load backup
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive text-sm"
                  disabled={isBusy}
                  onClick={() => setConfirmDelete(true)}
                >
                  delete
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
