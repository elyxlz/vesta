import { useEffect, useRef, useState } from "react";
import { LayoutGroup, motion } from "motion/react";
import { cn } from "@/lib/utils";
import type { AgentInfo } from "@/lib/types";
import { useOrbState } from "@/hooks/use-orb-state";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";
import { AgentIslandExpanded } from "./Expanded";
import { AgentIslandCollapsed } from "./Collapsed";
import { agentIslandContentTransition } from "./transitions";

const LEAVE_DELAY = 0;

const springTransition = { type: "spring" as const, bounce: 0.1, duration: 0.5 };

export function AgentIsland() {
  const { name, agent, agentState, operation, error } = useSelectedAgent();
  const { agents } = useAgents();
  const listEntry = agents.find((a) => a.name === name);
  const info = agent ?? listEntry ?? null;

  const orbState = useOrbState(info, agentState);
  const statusLabel = getStatusLabel(info, operation, error);

  const [expanded, setExpanded] = useState(false);
  const leaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const handleEnter = () => {
    if (leaveTimerRef.current) {
      clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
    setExpanded(true);
  };

  const scheduleCollapse = () => {
    leaveTimerRef.current = setTimeout(() => {
      setExpanded(false);
    }, LEAVE_DELAY);
  };

  const usesHoverPointer = (pointerType: string) =>
    pointerType === "mouse" || pointerType === "pen";

  const handlePointerEnter = (e: React.PointerEvent) => {
    if (usesHoverPointer(e.pointerType)) handleEnter();
  };

  const handlePointerLeave = (e: React.PointerEvent) => {
    if (!usesHoverPointer(e.pointerType)) return;
    const related = e.relatedTarget;
    if (related instanceof Element && related.closest("[data-agent-menu]")) return;
    scheduleCollapse();
  };

  useEffect(() => {
    if (!expanded) return;
    const onPointerDownCapture = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const root = rootRef.current;
      if (!root) return;
      const target = e.target;
      if (!(target instanceof Element)) return;
      if (root.contains(target)) return;
      if (target.closest('[data-slot="dropdown-menu-content"]')) return;
      if (target.closest('[data-slot="drawer-content"]')) return;
      if (target.closest('[data-slot="drawer-overlay"]')) return;
      if (target.closest("[data-agent-menu]")) return;
      if (target.closest('[data-slot="dialog-content"]')) return;
      if (target.closest('[data-slot="dialog-overlay"]')) return;
      if (target.closest('[data-slot="alert-dialog-content"]')) return;
      if (target.closest('[data-slot="alert-dialog-overlay"]')) return;
      setExpanded(false);
    };
    document.addEventListener("pointerdown", onPointerDownCapture, true);
    return () => document.removeEventListener("pointerdown", onPointerDownCapture, true);
  }, [expanded]);

  return (
    <div className="relative z-[99999] my-auto flex justify-center">
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

export function getStatusLabel(
  agent: Pick<AgentInfo, "alive" | "status" | "authenticated" | "agent_ready" | "friendly_status"> | null,
  operation: string,
  error: string,
): string {
  if (error) return error;

  switch (operation) {
    case "stopping":
      return "stopping...";
    case "starting":
      return "starting...";
    case "authenticating":
      return "signing in...";
    case "deleting":
      return "deleting...";
    case "rebuilding":
      return "rebuilding...";
    case "backing-up":
      return "backing up...";
    case "restoring":
      return "restoring...";
  }

  if (!agent) return "";

  if (agent.alive) return "alive";
  if (agent.status === "running" && agent.authenticated && !agent.agent_ready)
    return "waking up...";
  if (agent.status === "running" && !agent.authenticated) return "not signed in";
  if (agent.status === "stopped") return "stopped";
  if (agent.status === "dead") return "broken — delete and recreate";
  return agent.friendly_status || agent.status;
}
