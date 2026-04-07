import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authenticate, type AuthStartResult } from "@/api";
import type { AgentInfo } from "@/lib/types";
import { openExternalUrl } from "@/lib/open-external-url";
import { getOrbVisualState } from "@/components/Orb/styles";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";

const LEAVE_DELAY = 0;

export type UseAgentIslandOptions = {
  menuAnchoredInNavbar: boolean;
};

export function useAgentIsland({ menuAnchoredInNavbar }: UseAgentIslandOptions) {
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
    remove,
  } = useSelectedAgent();

  const { agents, refreshAgents } = useAgents();
  const listEntry = agents.find((a) => a.name === name);

  const [expanded, setExpanded] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [showConsole, setShowConsole] = useState(false);
  const [showAgentSettings, setShowAgentSettings] = useState(false);
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
    if (showAuth) return;
    scheduleCollapse();
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
    handleLeave();
  };

  const onMenuOpenChange = (open: boolean) => {
    setMenuOpen(open);
    if (!open && !menuAnchoredInNavbar) scheduleCollapse();
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

  const springTransition = { type: "spring" as const, bounce: 0.1, duration: 0.5 };

  return {
    name,
    info,
    orbState,
    statusLabel,
    error,
    operation,
    isBusy,
    expanded,
    setExpanded,
    deleteDialogOpen,
    setDeleteDialogOpen,
    menuOpen,
    showConsole,
    setShowConsole,
    showAgentSettings,
    setShowAgentSettings,
    showAuth,
    authStarting,
    authStart,
    authError,
    rootRef,
    springTransition,
    handlePointerEnter,
    handlePointerLeave,
    handleOpenAuth,
    clearAuthState,
    handleDelete,
    onMenuOpenChange,
    start,
    stop,
    restart,
    rebuild,
    backup,
    onShowBackups: () => {
      /* TODO: backups panel */
    },
    onShowConsole: () => setShowConsole(true),
    onShowAgentSettings: () => setShowAgentSettings(true),
    onOpenDeleteDialog: () => setDeleteDialogOpen(true),
  };
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
