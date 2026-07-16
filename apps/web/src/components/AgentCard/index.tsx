import { AnimatePresence, motion } from "motion/react";
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Orb } from "@/components/Orb";
import type { AgentInfo } from "@/lib/types";
import { useNavigate } from "react-router-dom";
import { useAgentOps, getOpLabel } from "@/stores/use-agent-ops";
import { useOrbStatus } from "@/hooks/use-orb-state";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: AgentInfo;
  enableTracking?: boolean;
}

export function AgentCard({ agent, enableTracking = false }: AgentCardProps) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  const opState = useAgentOps((s) => s.getOp(agent.name));
  const { orbState, label } = useOrbStatus(agent, agent.activityState);

  return (
    <Card className="flex items-center justify-center h-full w-full">
      <button
        type="button"
        aria-label={`open ${agent.name}`}
        onClick={() => {
          void navigate(`/agent/${agent.name}${isMobile ? "/chat" : ""}`);
        }}
        className="flex h-full w-full items-center justify-center rounded-squircle-md border border-transparent [corner-shape:squircle] outline-none transition-all hover:bg-muted/40 active:scale-[0.99] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
      >
        <CardContent className="flex flex-col items-center gap-3 px-5 pt-0 pb-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Orb
                  state={orbState}
                  size={112}
                  enableTracking={enableTracking}
                  label={`${agent.name}: ${label}`}
                />
              </span>
            </TooltipTrigger>
            {label && <TooltipContent>{label}</TooltipContent>}
          </Tooltip>
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
                    opState.error
                      ? "text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  {opState.error || getOpLabel(opState.operation)}
                </CardDescription>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </button>
    </Card>
  );
}
