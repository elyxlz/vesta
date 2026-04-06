import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import type { OrbVisualState } from "@/components/Orb/styles";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandCollapsedProps = {
  name: string;
  orbState: OrbVisualState;
  onExpand: () => void;
};

export function AgentIslandCollapsed({ name, orbState, onExpand }: AgentIslandCollapsedProps) {
  return (
    <div
      className="flex max-w-[min(100vw-2rem,320px)] cursor-pointer touch-manipulation items-center gap-1.5 py-2 px-5 will-change-transform"
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
        className="text-sm font-semibold leading-tight truncate min-w-0 flex-1 will-change-transform"
        transition={agentIslandContentTransition}
      >
        {name}
      </motion.span>
    </div>
  );
}
