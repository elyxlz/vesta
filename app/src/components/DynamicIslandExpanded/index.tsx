import {
  Activity,
  MoreVertical,
  Play,
  ScrollText,
  Settings,
  Square,
  KeyRound,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Spinner } from "@/components/ui/spinner";
import { ProgressBar } from "@/components/ProgressBar";
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
import { fadeSlide } from "@/lib/motion";
import type { AuthStartResult } from "@/api";
import type { AgentInfo } from "@/lib/types";
import type { OrbVisualState } from "@/components/Orb/styles";

type DynamicIslandExpandedProps = {
  name: string;
  info: Pick<AgentInfo, "status" | "authenticated" | "alive"> | null;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
  operation: string;
  isBusy: boolean;
  menuOpen: boolean;
  showAuth: boolean;
  authStarting: boolean;
  authStart: AuthStartResult | null;
  authError: string;
  onMenuOpenChange: (open: boolean) => void;
  onAuthOpen: () => void | Promise<void>;
  onAuthClear: () => void;
  onStart: () => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onRestart: () => void | Promise<void>;
  onRebuild: () => void | Promise<void>;
  onBackup: () => void | Promise<void>;
  onShowBackups: () => void;
  onShowConsole: () => void;
  onShowInternals: () => void;
  onShowAgentSettings: () => void;
  onOpenDeleteDialog: () => void;
};

export function DynamicIslandExpanded({
  name,
  info,
  orbState,
  statusLabel,
  error,
  operation,
  isBusy,
  menuOpen,
  showAuth,
  authStarting,
  authStart,
  authError,
  onMenuOpenChange,
  onAuthOpen,
  onAuthClear,
  onStart,
  onStop,
  onRestart,
  onRebuild,
  onBackup,
  onShowBackups,
  onShowConsole,
  onShowInternals,
  onShowAgentSettings,
  onOpenDeleteDialog,
}: DynamicIslandExpandedProps) {
  return (
    <div className="flex flex-col items-center gap-4 p-9 min-w-[300px]">
      <Orb state={orbState} size={100} enableTracking />

      <div className="text-center -mt-4">
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
                  onClick={onAuthClear}
                >
                  cancel
                </Button>
              </div>
            ) : authStart ? (
              <AuthFlow
                agentName={name}
                authUrl={authStart.auth_url}
                sessionId={authStart.session_id}
                onCancel={onAuthClear}
                onComplete={async () => {
                  onAuthClear();
                  await onRestart();
                }}
              />
            ) : (
              <div className="flex flex-col items-center gap-3 w-full max-w-[260px]">
                <p className="text-xs text-destructive">{authError || "authentication failed"}</p>
                <Button size="sm" onClick={onAuthOpen}>
                  retry
                </Button>
                <Button
                  variant="link"
                  size="sm"
                  onClick={onAuthClear}
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
                        onClick={onAuthOpen}
                      >
                        <KeyRound data-icon="inline-start" />
                        authenticate
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={isBusy}
                      onClick={info?.status === "running" ? onStop : onStart}
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
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={onShowConsole}
                        >
                          <ScrollText data-icon="inline-start" />
                          logs
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={onShowInternals}
                        >
                          <Activity data-icon="inline-start" />
                          internals
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={onShowAgentSettings}
                        >
                          <Settings data-icon="inline-start" />
                          settings
                        </Button>
                      </>
                    )}

                    <DropdownMenu open={menuOpen} onOpenChange={onMenuOpenChange}>
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
                                  onClick={onRestart}
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
                                  onClick={onRebuild}
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
                              onClick={onBackup}
                            >
                              backup
                            </DropdownMenuItem>
                          </TooltipTrigger>
                          <TooltipContent side="left">
                            create a snapshot
                          </TooltipContent>
                        </Tooltip>
                        <DropdownMenuItem
                          className="text-sm"
                          onClick={onShowBackups}
                        >
                          backups
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <DropdownMenuItem
                              className="text-destructive text-sm"
                              disabled={isBusy}
                              onClick={onOpenDeleteDialog}
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
    </div>
  );
}
