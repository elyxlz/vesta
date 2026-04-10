import { AnimatePresence, motion } from "motion/react";
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Orb } from "@/components/Orb";
import type { AgentInfo } from "@/lib/types";
import { useNavigate } from "react-router-dom";
import { useAgentOps, getOpLabel } from "@/stores/use-agent-ops";
import { useOrbState } from "@/hooks/use-orb-state";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: AgentInfo;
}

export function AgentCard({ agent }: AgentCardProps) {
  const navigate = useNavigate();

  const opState = useAgentOps((s) => s.getOp(agent.name));
  const orbState = useOrbState(agent, agent.activityState);

  return (
    <Card
      className="cursor-pointer flex items-center justify-center gap-3 h-full w-full"
      onClick={() => navigate(`/agent/${agent.name}`)}
    >
      <CardContent className="flex flex-col items-center gap-3 px-5 pt-0 pb-0">
        <Orb state={orbState} size={112} />
        <CardTitle className="font-serif text-center text-2xl -mt-3 font-medium tracking-tight text-foreground">
          {agent.name}
        </CardTitle>

        <AnimatePresence>
          {(opState.operation !== "idle" || opState.error) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.15 }}
              className="flex items-center gap-1.5"
            >
              {opState.operation !== "idle" && (
                <Spinner className="size-3 text-muted-foreground" />
              )}
              <CardDescription
                className={cn(
                  "text-xs",
                  opState.error ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {opState.error || getOpLabel(opState.operation)}
              </CardDescription>
            </motion.div>
          )}
        </AnimatePresence>
      </CardContent>
    </Card>
  );
}
