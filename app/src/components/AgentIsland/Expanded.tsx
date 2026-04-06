import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandExpandedProps = {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
};

export function AgentIslandExpanded({ name, orbState, statusLabel, error }: AgentIslandExpandedProps) {
  return (
    <div className="flex h-[168px] w-[200px] flex-col items-center justify-center gap-2 px-3 py-3 will-change-transform">
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb state={orbState} size={72} enableTracking />
      </motion.div>
      <div className="flex flex-col items-center justify-center gap-1 text-center -mt-2 will-change-transform">
        <motion.p
          layoutId="agent-island-name"
          layout
          className="text-sm font-semibold leading-tight line-clamp-2 px-0.5 will-change-transform"
          transition={agentIslandContentTransition}
        >
          {name}
        </motion.p>
        <motion.p
          className={cn(
            "text-xs leading-snug line-clamp-3 px-0.5 w-full will-change-[transform,opacity]",
            error ? "text-destructive" : "text-foreground/50",
          )}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ ...agentIslandContentTransition, delay: 0.1 }}
        >
          {statusLabel}
        </motion.p>
      </div>
    </div>
  );
}
