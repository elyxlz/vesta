import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandCollapsedProps = {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
};

export function AgentIslandCollapsed({
  name,
  orbState,
  statusLabel,
  error,
}: AgentIslandCollapsedProps) {
  const showStatus = statusLabel && statusLabel !== "alive";
  return (
    <div className="flex h-8 w-full min-w-0 items-center gap-1.5 will-change-transform">
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb
          state={orbState}
          size={28}
          suppressMotion
          label={`${name}: ${statusLabel || orbState}`}
        />
      </motion.div>
      <div className="relative -top-0.5 min-w-0 flex-1 flex items-baseline gap-1.5">
        <motion.span
          layoutId="agent-island-name"
          layout
          className="min-w-0 truncate font-serif text-base sm:text-lg font-medium leading-tight tracking-tight will-change-transform"
          transition={agentIslandContentTransition}
        >
          {name}
        </motion.span>
        {showStatus && (
          <motion.span
            layoutId="agent-island-status"
            layout
            transition={agentIslandContentTransition}
            className={cn(
              "shrink-0 text-xs will-change-transform",
              error ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {statusLabel}
          </motion.span>
        )}
      </div>
      {/* persistent live region so screen readers hear status changes even when collapsed */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {statusLabel}
      </span>
    </div>
  );
}
