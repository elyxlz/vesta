import { LayoutGroup, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { useAgentIsland } from "@/hooks/use-agent-island";
import { AgentIslandExpanded } from "./Expanded";
import { AgentIslandCollapsed } from "./Collapsed";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandProps = Pick<
  ReturnType<typeof useAgentIsland>,
  | "name"
  | "orbState"
  | "statusLabel"
  | "error"
  | "rootRef"
  | "springTransition"
  | "handlePointerEnter"
  | "handlePointerLeave"
  | "expanded"
  | "setExpanded"
>;

export function AgentIsland(props: AgentIslandProps) {
  const {
    name,
    orbState,
    statusLabel,
    error,
    rootRef,
    springTransition,
    handlePointerEnter,
    handlePointerLeave,
    expanded,
    setExpanded,
  } = props;

  return (
    <div className="relative my-auto flex justify-center">
      <motion.div
        ref={rootRef}
        layout
        transition={springTransition}
        style={{ borderRadius: 16 }}
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        className={cn(
          "mx-auto w-fit overflow-hidden bg-card border will-change-[transform,opacity]",
          expanded ? "shadow-xl" : "shadow-none",
        )}
      >
        <LayoutGroup id="agent-island">
          <motion.div
            transition={agentIslandContentTransition}
            className="will-change-[transform,opacity]"
            initial={{ scale: 0.9, opacity: 0, filter: "blur(4px)" }}
            animate={{
              scale: 1,
              opacity: 1,
              filter: "blur(0px)",
              transition: { ...agentIslandContentTransition, delay: 0.05 },
            }}
          >
            {expanded ? (
              <AgentIslandExpanded name={name} orbState={orbState} statusLabel={statusLabel} error={error} />
            ) : (
              <AgentIslandCollapsed name={name} orbState={orbState} onExpand={() => setExpanded(true)} />
            )}
          </motion.div>
        </LayoutGroup>
      </motion.div>
    </div>
  );
}
