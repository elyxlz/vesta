import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { AgentCard } from "@/components/AgentCard";
import { wsUrl } from "@/lib/connection";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { AgentActivityState } from "@/lib/types";
import { useAgents } from "@/providers/AgentsProvider";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";

export function Home() {
  const { agents, agentsLoaded, refreshAgents, setAgents } = useAgents();
  const navigate = useNavigate();

  const [activityStates, setActivityStates] = useState<
    Record<string, AgentActivityState>
  >({});
  const wsRefs = useRef<Map<string, WebSocket>>(new Map());

  const fetchAgents = async () => {
    const list = await refreshAgents();
    setAgents(list);
  };

  useEffect(() => {
    fetchAgents();
    const interval = setInterval(fetchAgents, 5000);
    return () => clearInterval(interval);
  }, [fetchAgents]);

  useEffect(() => {
    if (agentsLoaded && agents.length === 0) {
      navigate("/new");
    }
  }, [agentsLoaded, agents, navigate]);

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

  if (!agentsLoaded || agents.length === 0) return null;

  const gridCols =
    agents.length === 1
      ? "grid-cols-1 max-w-[300px]"
      : agents.length === 2
        ? "grid-cols-2 max-w-[520px]"
        : "grid-cols-3";

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 flex items-center justify-center overflow-y-auto px-4">
        <motion.div
          className={cn("grid gap-6 mx-auto", gridCols)}
          variants={staggerContainer}
          initial="hidden"
          animate="show"
        >
          {agents.map((agent) => (
            <motion.div key={agent.name} variants={staggerItem}>
              <AgentCard
                agent={agent}
                activityState={activityStates[agent.name] ?? "idle"}
              />
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  );
}
