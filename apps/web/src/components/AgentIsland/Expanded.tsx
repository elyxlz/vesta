import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import { CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandExpandedProps = {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
};

export function AgentIslandExpanded({
  name,
  orbState,
  statusLabel,
  error,
}: AgentIslandExpandedProps) {
  return (
    <div className="flex h-[168px] w-[168px] flex-col items-center justify-center gap-2 will-change-transform">
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb state={orbState} size={100} enableTracking />
      </motion.div>
      <div className="-mt-2 flex flex-col items-center justify-center gap-1 text-center will-change-transform">
        <motion.div
          layoutId="agent-island-name"
          layout
          transition={agentIslandContentTransition}
        >
          <CardTitle className="line-clamp-2 px-0.5 text-center font-serif font-medium leading-tight tracking-tight">
            {name}
          </CardTitle>
        </motion.div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ ...agentIslandContentTransition, delay: 0.1 }}
        >
          <CardDescription
            className={cn(
              "line-clamp-3 w-full px-0.5 text-xs leading-snug",
              error ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {statusLabel}
          </CardDescription>
        </motion.div>
      </div>
    </div>
  );
}
