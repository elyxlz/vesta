import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandCollapsedProps = {
  name: string;
  orbState: OrbVisualState;
  onExpand: () => void;
};

export function AgentIslandCollapsed({
  name,
  orbState,
  onExpand,
}: AgentIslandCollapsedProps) {
  return (
    <div
      className="flex h-8 w-full min-w-0 cursor-pointer touch-manipulation items-center gap-1.5 will-change-transform"
      onPointerDown={(event) => {
        if (event.pointerType === "touch") {
          onExpand();
        }
      }}
    >
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb state={orbState} size={28} suppressMotion />
      </motion.div>
      <motion.span
        layoutId="agent-island-name"
        layout
        className="min-w-0 flex-1 truncate font-serif text-lg font-medium leading-tight tracking-tight will-change-transform"
        transition={agentIslandContentTransition}
      >
        {name}
      </motion.span>
    </div>
  );
}
