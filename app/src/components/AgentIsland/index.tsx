import { useEffect, useRef, useState } from "react";
import { LayoutGroup, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { useOrbState } from "@/hooks/use-orb-state";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";
import { AgentIslandExpanded } from "./Expanded";
import { AgentIslandCollapsed } from "./Collapsed";
import { agentIslandContentTransition } from "./transitions";

const springTransition = {
  type: "spring" as const,
  bounce: 0.1,
  duration: 0.5,
};

const COLLAPSED_RADIUS = 22;
const EXPANDED_RADIUS = 22;

export function AgentIsland() {
  const { name, agent, agentState, error, statusLabel } = useSelectedAgent();
  const { agents } = useAgents();
  const listEntry = agents.find((a) => a.name === name);
  const info = agent ?? listEntry ?? null;

  const orbState = useOrbState(info, agentState);

  const [expanded, setExpanded] = useState(false);
  const islandRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!expanded) return;
    function handlePointerDown(e: PointerEvent) {
      if (islandRef.current && !islandRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [expanded]);

  return (
    <div
      ref={islandRef}
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") setExpanded(true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") setExpanded(false);
      }}
      className={cn(
        "relative z-[999999] flex justify-center overflow-visible",
        expanded ? "h-auto min-h-0" : "h-10",
      )}
    >
      <motion.div
        layout
        transition={springTransition}
        initial={{
          borderRadius: COLLAPSED_RADIUS,
        }}
        animate={{
          borderRadius: expanded ? EXPANDED_RADIUS : COLLAPSED_RADIUS,
        }}
        className={cn(
          "mx-auto will-change-[transform,opacity]",
          "border border-border bg-card text-base text-card-foreground shadow-sm",
          expanded
            ? "aspect-square w-[min(100vw-2rem,178px)] shrink-0 overflow-visible"
            : "h-full w-fit max-w-[min(100vw-2rem,158px)] overflow-hidden flex items-center",
        )}
      >
        <div
          className={cn(
            expanded
              ? "flex size-full flex-col items-center justify-center px-1 py-1"
              : "flex h-full items-center px-5 py-0",
          )}
        >
          <LayoutGroup id="agent-island">
            <motion.div
              transition={agentIslandContentTransition}
              className="will-change-[transform,opacity]"
              initial={{ opacity: 0 }}
              animate={{
                opacity: 1,
                transition: { ...agentIslandContentTransition, delay: 0.05 },
              }}
            >
              {expanded ? (
                <AgentIslandExpanded
                  name={name}
                  orbState={orbState}
                  statusLabel={statusLabel}
                  error={error}
                />
              ) : (
                <AgentIslandCollapsed
                  name={name}
                  orbState={orbState}
                  onExpand={() => setExpanded(true)}
                />
              )}
            </motion.div>
          </LayoutGroup>
        </div>
      </motion.div>
    </div>
  );
}
