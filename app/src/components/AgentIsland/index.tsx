import { useEffect, useRef, useState } from "react";
import { LayoutGroup, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { AgentIslandExpanded } from "./Expanded";
import { AgentIslandCollapsed } from "./Collapsed";
const springTransition = {
  type: "spring" as const,
  bounce: 0.1,
  duration: 0.5,
};

const BORDER_RADIUS = 22;

export function AgentIsland() {
  const { name, error, statusLabel, orbState } = useSelectedAgent();

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
          borderRadius: BORDER_RADIUS,
        }}
        animate={{
          borderRadius: expanded ? BORDER_RADIUS : BORDER_RADIUS,
        }}
        className={cn(
          "mx-auto will-change-[transform,opacity]",
          "border border-border bg-popover text-base text-popover-foreground shadow-sm",
          expanded
            ? "aspect-square w-[min(100vw-2rem,178px)] shrink-0 overflow-visible"
            : "h-full w-fit max-w-[min(100vw-2rem,280px)] overflow-hidden flex items-center",
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
            <div className="will-change-transform">
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
            </div>
          </LayoutGroup>
        </div>
      </motion.div>
    </div>
  );
}
