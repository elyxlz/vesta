import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Console } from "@/components/Console";
import { isTauri } from "@/lib/env";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { authenticate, type AuthStartResult } from "@/api";
import type { AgentInfo } from "@/lib/types";
import { openExternalUrl } from "@/lib/open-external-url";
import { useNavigate } from "react-router-dom";
import { getOrbVisualState } from "@/components/Orb/styles";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";
import { DynamicIslandExpanded } from "@/components/DynamicIslandExpanded";
import { DynamicIslandCollapsed } from "@/components/DynamicIslandCollapsed";

const LEAVE_DELAY = 0;

export function DynamicIsland() {
  const navigate = useNavigate();
  const {
    name,
    agent,
    agentState,
    operation,
    error,
    isBusy,
    start,
    stop,
    restart,
    rebuild,
    backup,
    restore,
    remove,
  } = useSelectedAgent();

  const { agents } = useAgents();
  const listEntry = agents.find((a) => a.name === name);

  const [expanded, setExpanded] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showConsole, setShowConsole] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [authStarting, setAuthStarting] = useState(false);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authError, setAuthError] = useState("");
  const authAttemptRef = useRef(0);
  const leaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const info = agent ?? listEntry ?? null;

  const orbState = info
    ? getOrbVisualState(
      info.status,
      info.authenticated,
      info.agent_ready,
      agentState,
      operation,
    )
    : "dead";

  const statusLabel = getStatusLabel(info, operation, error);

  const { refreshAgents } = useAgents();

  const handleDelete = async () => {
    await remove();
    await refreshAgents();
    navigate("/");
  };

  const clearAuthState = () => {
    authAttemptRef.current += 1;
    setShowAuth(false);
    setAuthStarting(false);
    setAuthStart(null);
    setAuthError("");
  };

  const handleOpenAuth = async () => {
    if (!name || authStarting) return;

    const attemptId = authAttemptRef.current + 1;
    authAttemptRef.current = attemptId;
    setShowAuth(true);
    setAuthStarting(true);
    setAuthStart(null);
    setAuthError("");

    try {
      const result = await authenticate(name);
      if (authAttemptRef.current !== attemptId) return;
      setAuthStart(result);
      void openExternalUrl(result.auth_url);
    } catch (e: unknown) {
      if (authAttemptRef.current !== attemptId) return;
      setAuthError((e as { message?: string })?.message || "authentication failed");
    } finally {
      if (authAttemptRef.current === attemptId) {
        setAuthStarting(false);
      }
    }
  };

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

  const handleLeave = () => {
    if (menuOpen) return;
    scheduleCollapse();
  };

  const usesHoverPointer = (pointerType: string) =>
    pointerType === "mouse" || pointerType === "pen";

  const handlePointerEnter = (e: React.PointerEvent) => {
    if (usesHoverPointer(e.pointerType)) handleEnter();
  };

  const handlePointerLeave = (e: React.PointerEvent) => {
    if (usesHoverPointer(e.pointerType)) handleLeave();
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
      if (target.closest('[data-slot="alert-dialog-content"]')) return;
      if (target.closest('[data-slot="alert-dialog-overlay"]')) return;
      setExpanded(false);
    };
    document.addEventListener("pointerdown", onPointerDownCapture, true);
    return () => document.removeEventListener("pointerdown", onPointerDownCapture, true);
  }, [expanded]);

  const view = expanded ? "expanded" : "collapsed";

  const springTransition = { type: "spring" as const, bounce: 0.1, duration: 0.5 };

  return (
    <div className="relative my-auto flex justify-center">
      <motion.div
        ref={rootRef}
        layout
        transition={springTransition}
        style={{ borderRadius: 16, willChange: "transform, opacity" }}
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        className={cn(
          "mx-auto w-fit overflow-hidden bg-card border",
          expanded ? "shadow-xl" : "shadow-none",
        )}
      >
        <motion.div
          key={view}
          transition={springTransition}
          style={{ willChange: "transform, opacity" }}
          initial={{ scale: 0.9, opacity: 0, filter: "blur(4px)" }}
          animate={{
            scale: 1,
            opacity: 1,
            filter: "blur(0px)",
            transition: { ...springTransition, delay: 0.05 },
          }}
        >
          {expanded ? (
            <DynamicIslandExpanded
              name={name}
              info={info}
              orbState={orbState}
              statusLabel={statusLabel}
              error={error}
              operation={operation}
              isBusy={isBusy}
              menuOpen={menuOpen}
              showAuth={showAuth}
              authStarting={authStarting}
              authStart={authStart}
              authError={authError}
              onMenuOpenChange={(open) => {
                setMenuOpen(open);
                if (!open) scheduleCollapse();
              }}
              onAuthOpen={handleOpenAuth}
              onAuthClear={clearAuthState}
              onStart={start}
              onStop={stop}
              onRestart={restart}
              onRebuild={rebuild}
              onBackup={backup}
              onRestore={restore}
              onShowConsole={() => setShowConsole(true)}
              onOpenDeleteDialog={() => setDeleteDialogOpen(true)}
            />
          ) : (
            <DynamicIslandCollapsed
              name={name}
              operation={operation}
              orbState={orbState}
              onExpand={() => setExpanded(true)}
            />
          )}
        </motion.div>
      </motion.div>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>delete {name}?</AlertDialogTitle>
            <AlertDialogDescription>
              this will permanently destroy the agent and all its data. this action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={handleDelete}
            >
              delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {createPortal(
        <AnimatePresence>
          {showConsole && info?.alive && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className={cn("fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-5", isTauri && "pt-7")}
              onClick={(e) => {
                if (e.target === e.currentTarget) setShowConsole(false);
              }}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex min-h-0 min-w-0 w-full h-full max-w-4xl max-h-[800px] flex-col dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8] rounded-none sm:rounded-xl overflow-hidden shadow-2xl"
              >
                <Console
                  name={name}
                  onClose={() => setShowConsole(false)}
                />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  );
}

function getStatusLabel(
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
