import { useEffect, useRef, useState } from "react";
import {
  MoreVertical,
  Play,
  ScrollText,
  Square,
  KeyRound,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Spinner } from "@/components/ui/spinner";
import { ProgressBar } from "@/components/ProgressBar";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Orb } from "@/components/Orb";
import { AuthFlow } from "@/components/AuthFlow";
import { cn } from "@/lib/utils";
import { authenticate, type AuthStartResult } from "@/api";
import type { AgentInfo } from "@/lib/types";
import { fadeSlide } from "@/lib/motion";
import { openExternalUrl } from "@/lib/open-external-url";
import { useNavigate } from "react-router-dom";
import { getOrbVisualState, orbColors } from "@/components/Orb/styles";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";

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

  return (
    <div
      ref={rootRef}
      className="relative my-auto"
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
    >
      <motion.div
        layout
        className={cn(
          "origin-top bg-card border rounded-2xl shadow-lg overflow-hidden",
          expanded && "shadow-xl",
        )}
        transition={{ type: "spring", stiffness: 400, damping: 30 }}
      >
        <AnimatePresence mode="wait" initial={false}>
          {expanded ? (
            <motion.div
              key="expanded"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.1 }}
              className="flex flex-col items-center gap-3 p-9 min-w-[300px]"
            >
              <Orb state={orbState} size={100} enableTracking />

              <div className="text-center">
                <p className="text-sm font-semibold leading-none">{name}</p>
                <p
                  className={cn(
                    "text-xs leading-none mt-1",
                    error ? "text-destructive" : "text-foreground/50",
                  )}
                >
                  {statusLabel}
                </p>
              </div>

              <AnimatePresence mode="wait">
                {showAuth && info?.status === "running" ? (
                  <motion.div key="auth" {...fadeSlide}>
                    {authStarting ? (
                      <div className="flex flex-col items-center gap-3 w-full max-w-[260px]">
                        <p className="text-sm text-muted-foreground">starting authentication...</p>
                        <ProgressBar message="waiting..." />
                        <Button
                          variant="link"
                          size="sm"
                          onClick={clearAuthState}
                        >
                          cancel
                        </Button>
                      </div>
                    ) : authStart ? (
                      <AuthFlow
                        agentName={name}
                        authUrl={authStart.auth_url}
                        sessionId={authStart.session_id}
                        onCancel={clearAuthState}
                        onComplete={async () => {
                          clearAuthState();
                          await restart();
                        }}
                      />
                    ) : (
                      <div className="flex flex-col items-center gap-3 w-full max-w-[260px]">
                        <p className="text-xs text-destructive">{authError || "authentication failed"}</p>
                        <Button size="sm" onClick={handleOpenAuth}>
                          retry
                        </Button>
                        <Button
                          variant="link"
                          size="sm"
                          onClick={clearAuthState}
                        >
                          cancel
                        </Button>
                      </div>
                    )}
                  </motion.div>
                ) : !showAuth ? (
                  <div className="flex items-center justify-center gap-2 h-8">
                    <AnimatePresence mode="wait">
                      {operation !== "idle" ? (
                        <motion.div
                          key="busy"
                          {...fadeSlide}
                          className="flex items-center justify-center"
                        >
                          <Spinner className="size-[18px] text-foreground/40" />
                        </motion.div>
                      ) : (
                        <motion.div key="normal" {...fadeSlide} className="flex items-center gap-2">
                          <ButtonGroup>
                            {info?.status === "running" && !info.authenticated && (
                              <Button
                                size="sm"
                                onClick={handleOpenAuth}
                              >
                                <KeyRound data-icon="inline-start" />
                                authenticate
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isBusy}
                              onClick={
                                info?.status === "running" ? stop : start
                              }
                            >
                              {info?.status === "running" ? (
                                <>
                                  <Square data-icon="inline-start" />
                                  stop
                                </>
                              ) : (
                                <>
                                  <Play data-icon="inline-start" />
                                  start
                                </>
                              )}
                            </Button>

                            {info?.alive && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  window.dispatchEvent(new CustomEvent("open-console"));
                                }}
                              >
                                <ScrollText data-icon="inline-start" />
                                logs
                              </Button>
                            )}

                            <DropdownMenu open={menuOpen} onOpenChange={(open) => {
                              setMenuOpen(open);
                              if (!open) scheduleCollapse();
                            }}>
                              <DropdownMenuTrigger asChild>
                                <Button size="icon-sm" variant="outline">
                                  <MoreVertical />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent
                                align="center"
                                side="bottom"
                                className="min-w-[150px]"
                              >
                                {info?.status === "running" && (
                                  <>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <DropdownMenuItem
                                          className="text-sm"
                                          disabled={isBusy}
                                          onClick={restart}
                                        >
                                          restart
                                        </DropdownMenuItem>
                                      </TooltipTrigger>
                                      <TooltipContent side="left">
                                        restart agent
                                      </TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <DropdownMenuItem
                                          className="text-sm"
                                          disabled={isBusy}
                                          onClick={rebuild}
                                        >
                                          rebuild
                                        </DropdownMenuItem>
                                      </TooltipTrigger>
                                      <TooltipContent side="left">
                                        rebuild container from latest image
                                      </TooltipContent>
                                    </Tooltip>
                                  </>
                                )}
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <DropdownMenuItem
                                      className="text-sm"
                                      disabled={isBusy}
                                      onClick={backup}
                                    >
                                      backup
                                    </DropdownMenuItem>
                                  </TooltipTrigger>
                                  <TooltipContent side="left">
                                    export to file
                                  </TooltipContent>
                                </Tooltip>
                                <DropdownMenuItem
                                  className="text-sm"
                                  disabled={isBusy}
                                  onClick={restore}
                                >
                                  load backup
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <DropdownMenuItem
                                      className="text-destructive text-sm"
                                      disabled={isBusy}
                                      onClick={() => setDeleteDialogOpen(true)}
                                    >
                                      delete
                                    </DropdownMenuItem>
                                  </TooltipTrigger>
                                  <TooltipContent side="left">
                                    permanently delete
                                  </TooltipContent>
                                </Tooltip>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </ButtonGroup>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ) : null}
              </AnimatePresence>
            </motion.div>
          ) : (
            <motion.div
              key="collapsed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.1 }}
              className="flex items-center gap-2.5 py-3 px-12 cursor-pointer touch-manipulation"
              onPointerDown={(e) => {
                if (e.pointerType === "touch") {
                  setExpanded(true);
                }
              }}
            >
              <motion.div
                className="rounded-full shrink-0"
                style={{ width: 14, height: 14, backgroundColor: orbColors[orbState][1] }}
                animate={{
                  backgroundColor: orbColors[orbState][1],
                  boxShadow: `0 0 8px 2px ${orbColors[orbState][1]}`,
                }}
                transition={{ duration: 1 }}
              />
              <div className="flex items-center gap-2">
                <span className="text-sm leading-tight font-semibold whitespace-nowrap">{name}</span>
                {operation !== "idle" && (
                  <Spinner className="size-3 text-foreground/40" />
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
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
