import { AnimatePresence, motion } from "motion/react";
import { Spinner } from "@/components/ui/spinner";
import { Orb } from "@/components/Orb";
import type { ListEntry, AgentActivityState } from "@/lib/types";
import { useNavigate } from "react-router-dom";
import { useAgentOps, getOpLabel } from "@/stores/use-agent-ops";
import { useOrbState } from "@/hooks/use-orb-state";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: ListEntry;
  activityState: AgentActivityState;
}

export function AgentCard({ agent, activityState }: AgentCardProps) {
  const navigate = useNavigate();

  const opState = useAgentOps((s) => s.getOp(agent.name));
  const orbState = useOrbState(agent, activityState);

  return (
    <div
      className="flex flex-col items-center gap-3 p-5 cursor-pointer"
      onClick={() => navigate(`/agent/${agent.name}`)}
    >
      <Orb state={orbState} size={112} />
      <span className="text-2xl font-medium text-foreground">
        {agent.name}
      </span>

      <AnimatePresence>
        {(opState.operation !== "idle" || opState.error) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.15 }}
            className={cn(
              "flex items-center gap-1.5 text-xs",
              opState.error ? "text-destructive" : "text-foreground/50",
            )}
          >
            {opState.operation !== "idle" && (
              <Spinner className="size-3" />
            )}
            <span>{opState.error || getOpLabel(opState.operation)}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
