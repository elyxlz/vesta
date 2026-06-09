import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandCollapsedProps = {
  name: string;
  orbState: OrbVisualState;
  expanded: boolean;
  onExpand: () => void;
  statusLabel: string;
  error: string;
};

export function AgentIslandCollapsed({
  name,
  orbState,
  expanded,
  onExpand,
  statusLabel,
  error,
}: AgentIslandCollapsedProps) {
  const showStatus = statusLabel && statusLabel !== "alive";
  return (
    <button
      type="button"
      className="flex h-8 w-full min-w-0 cursor-pointer touch-manipulation items-center gap-1.5 bg-transparent will-change-transform"
      aria-expanded={expanded}
      aria-label={`${name}, ${orbState}`}
      onClick={onExpand}
      onFocus={onExpand}
    >
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb state={orbState} size={28} suppressMotion />
      </motion.div>
      <div className="min-w-0 flex-1 flex items-center gap-1.5">
        <motion.span
          layoutId="agent-island-name"
          layout
          className="min-w-0 truncate font-serif text-base sm:text-lg font-medium leading-tight tracking-tight will-change-transform"
          transition={agentIslandContentTransition}
        >
          {name}
        </motion.span>
        {showStatus && (
          <span
            className={cn(
              "shrink-0 text-xs",
              error ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {statusLabel}
          </span>
        )}
      </div>
      {/* persistent live region so screen readers hear status changes even when collapsed */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {statusLabel}
      </span>
    </button>
  );
}
