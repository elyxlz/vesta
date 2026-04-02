import { useCallback, useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { AgentCard } from "@/components/AgentCard";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { listAgents } from "@/api";
import { wsUrl } from "@/lib/connection";
import type { AgentActivityState } from "@/lib/types";
import { useAppStore } from "@/stores/use-app-store";
import { useNavigation } from "@/stores/use-navigation";
import { cn } from "@/lib/utils";

export function Home() {
  const agents = useAppStore((s) => s.agents);
  const setAgents = useAppStore((s) => s.setAgents);
  const version = useAppStore((s) => s.version);
  const navigateToCreate = useNavigation((s) => s.navigateToCreate);

  const [activityStates, setActivityStates] = useState<
    Record<string, AgentActivityState>
  >({});
  const [fetched, setFetched] = useState(false);
  const wsRefs = useRef<Map<string, WebSocket>>(new Map());

  const fetchAgents = useCallback(async () => {
    try {
      const list = await listAgents();
      setAgents(list);
      setFetched(true);
    } catch {
      // ignore polling errors
    }
  }, [setAgents]);

  useEffect(() => {
    fetchAgents();
    const interval = setInterval(fetchAgents, 5000);
    return () => clearInterval(interval);
  }, [fetchAgents]);

  useEffect(() => {
    if (fetched && agents.length === 0) {
      navigateToCreate();
    }
  }, [fetched, agents, navigateToCreate]);

  useEffect(() => {
    const aliveNames = new Set(
      agents.filter((a) => a.alive).map((a) => a.name),
    );
    const current = wsRefs.current;

    for (const [name, ws] of current.entries()) {
      if (!aliveNames.has(name)) {
        ws.close();
        current.delete(name);
      }
    }

    for (const name of aliveNames) {
      if (current.has(name)) continue;
      try {
        const url = wsUrl(name);
        const ws = new WebSocket(url);
        current.set(name, ws);
        ws.onmessage = (e) => {
          if (typeof e.data !== "string") return;
          try {
            const data = JSON.parse(e.data);
            if (data.type === "status") {
              setActivityStates((prev) => ({ ...prev, [name]: data.state }));
            } else if (data.type === "history" && data.state) {
              setActivityStates((prev) => ({ ...prev, [name]: data.state }));
            }
          } catch {
            // ignore
          }
        };
        ws.onclose = () => {
          current.delete(name);
        };
      } catch {
        // ignore ws errors
      }
    }

    return () => {
      for (const ws of current.values()) ws.close();
      current.clear();
    };
  }, [agents]);

  if (!fetched || agents.length === 0) return null;

  const gridCols =
    agents.length === 1
      ? "grid-cols-1 max-w-[180px]"
      : agents.length === 2
        ? "grid-cols-2 max-w-[320px]"
        : "grid-cols-3";

  return (
    <div className="flex flex-col h-full animate-view-in">
      <div className="flex items-center justify-end px-4 pt-1 pb-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={navigateToCreate}
            >
              <Plus size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>new agent</TooltipContent>
        </Tooltip>
      </div>

      <div className="flex-1 flex items-center justify-center overflow-y-auto px-4">
        <div className={cn("grid gap-2 mx-auto", gridCols)}>
          {agents.map((agent) => (
            <AgentCard
              key={agent.name}
              agent={agent}
              activityState={activityStates[agent.name] ?? "idle"}
            />
          ))}
        </div>
      </div>

      {version && (
        <div className="text-center pb-3">
          <span className="text-xs text-muted-foreground">v{version}</span>
        </div>
      )}
    </div>
  );
}
