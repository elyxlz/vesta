import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { resolveProviderIdentity } from "@vesta/core";
import { cn } from "@/lib/utils";
import { useProvider } from "@/hooks/use-provider";
import { useManifest } from "@/hooks/use-manifest";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { AgentIslandExpanded } from "./Expanded";
import { AgentIslandCollapsed } from "./Collapsed";

const springTransition = {
  type: "spring" as const,
  bounce: 0.1,
  duration: 0.35,
};

const BORDER_RADIUS = 22;

// The container springs its size between the two states; the active view fades
// in. No exit animation — the outgoing view is simply replaced.
const enterVariants = {
  initial: { opacity: 0.6 },
  animate: {
    opacity: 1,
    transition: { delay: 0.05 },
  },
};

export function AgentIsland() {
  const { name, error, statusLabel, orbState } = useSelectedAgent();
  const { provider } = useProvider(name);
  const manifest = useManifest();
  const providerIdentity = resolveProviderIdentity(provider, manifest);

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

  const view = expanded ? "expanded" : "collapsed";
  const content = expanded ? (
    <AgentIslandExpanded
      name={name}
      orbState={orbState}
      statusLabel={statusLabel}
      error={error}
      providerIdentity={providerIdentity}
    />
  ) : (
    <AgentIslandCollapsed
      name={name}
      orbState={orbState}
      statusLabel={statusLabel}
      error={error}
    />
  );

  return (
    <div
      ref={islandRef}
      onKeyDown={(e) => {
        if (e.key === "Escape") setExpanded(false);
      }}
      onBlur={(e) => {
        if (!islandRef.current?.contains(e.relatedTarget)) {
          setExpanded(false);
        }
      }}
      className="relative z-[999999] flex h-10 justify-center overflow-visible"
    >
      <motion.div
        layout
        transition={springTransition}
        initial={{ borderRadius: BORDER_RADIUS }}
        animate={{ borderRadius: BORDER_RADIUS }}
        role={expanded ? undefined : "button"}
        tabIndex={expanded ? -1 : 0}
        aria-expanded={expanded}
        aria-label={
          expanded ? undefined : `${name}, ${statusLabel || orbState}`
        }
        onClick={expanded ? undefined : () => setExpanded(true)}
        onFocus={expanded ? undefined : () => setExpanded(true)}
        onKeyDown={
          expanded
            ? undefined
            : (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpanded(true);
                }
              }
        }
        className={cn(
          "chrome-outline flex items-center justify-center overflow-hidden bg-clip-padding text-base text-popover-foreground will-change-[transform,opacity]",
          expanded
            ? "absolute top-0 left-1/2 aspect-square w-[min(100vw-2rem,178px)] shrink-0 -translate-x-1/2"
            : "mx-auto h-full w-fit max-w-[min(100vw-2rem,280px)] cursor-pointer touch-manipulation",
        )}
      >
        {/* Active view: keyed so it remounts and plays the enter animation. */}
        <motion.div
          key={view}
          variants={enterVariants}
          initial="initial"
          animate="animate"
          transition={springTransition}
        >
          {content}
        </motion.div>
      </motion.div>
    </div>
  );
}
