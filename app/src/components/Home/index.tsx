import { motion } from "motion/react";
import { AgentCard } from "@/components/AgentCard";
import { staggerContainer, staggerItem } from "@/lib/motion";
import { useAgents } from "@/providers/AgentsProvider";
import { cn } from "@/lib/utils";

export function Home() {
  const { agents, agentsLoaded, activityStates } = useAgents();

  if (!agentsLoaded || agents.length === 0) return null;

  const gridCols =
    agents.length === 1
      ? "grid-cols-1 max-w-[300px]"
      : agents.length === 2
        ? "grid-cols-2 max-w-[520px]"
        : "grid-cols-3";

  return (
    <div className="flex min-h-0 w-full flex-1 items-center justify-center overflow-y-auto px-4">
      <motion.div
        className={cn("grid gap-8 mx-auto", gridCols)}
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
  );
}
