import { useState } from "react";
import {
  ArrowLeftRight,
  MoreHorizontal,
  RefreshCw,
  LogOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ProgressBar } from "@/components/ProgressBar";
import { ModelStep } from "@/components/ProviderPicker/ModelStep";
import { ContextStep } from "@/components/ProviderPicker/ContextStep";
import { providerMeta } from "@/components/ProviderPicker/providers";
import {
  setModel,
  setContextWindow,
  signOutProvider,
  type UsageMeter,
} from "@/api/agents";
import { formatTokens } from "@/lib/format";
import { errorMessage } from "@/lib/utils";
import { useProvider } from "@/hooks/use-provider";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { useManifest } from "@/hooks/use-manifest";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";
import { useUsage } from "./use-usage";

function formatResetsAt(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "now";
  const hours = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `in ${hours}h ${mins}m`;
  return `in ${mins}m`;
}

function UsageBar({ meter }: { meter: UsageMeter }) {
  const pct = meter.used_pct != null ? Math.min(meter.used_pct, 100) : null;
  const resetsAt = meter.resets_at ? formatResetsAt(meter.resets_at) : null;

  if (pct == null) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{meter.label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {pct.toFixed(0)}%
        </span>
      </div>
      <Progress value={pct} className="h-1.5" />
      {resetsAt && (
        <span className="text-[10px] text-muted-foreground/60">
          Resets {resetsAt}
        </span>
      )}
    </div>
  );
}

/// Provider hub for an agent: shows the current provider, model, context
/// window, and plan usage; lets you switch between Claude and OpenRouter
/// (reuses the reconfigure modal), change the model, and change the context
/// window — each without re-entering credentials.
export function ProviderCard() {
  const { name, agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  // Revalidate on status change so a provider switch (which restarts the agent)
  // is reflected here without a manual reload.
  const { provider, refresh } = useProvider(name, agent?.status);
  const claudeModels = useClaudeModels(provider?.kind === "claude");
  // Context-window presets come from the manifest (GET /manifest); the context dialog needs the
  // active provider's presets just like the setup wizard does.
  const manifest = useManifest();
  const [modelOpen, setModelOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    usage,
    loading: usageLoading,
    error: usageError,
    refresh: refreshUsage,
  } = useUsage(name);

  if (!provider || provider.kind === "none") return null;

  const isOpenRouter = provider.kind === "openrouter";
  const { Logo } = providerMeta(provider.kind);
  const contextLabel =
    provider.max_context_tokens != null
      ? `${formatTokens(provider.max_context_tokens)} context`
      : isOpenRouter
        ? "default context"
        : "1M context";

  const meters = usage?.meters ?? [];
  const credits = usage?.credits ?? null;

  const runAction = async (action: () => Promise<void>, fallback: string) => {
    if (!name) return;
    setApplying(true);
    setError(null);
    try {
      await action();
      refresh();
    } catch (e) {
      setError(errorMessage(e, fallback));
    } finally {
      setApplying(false);
    }
  };

  const applyModel = (model: string) =>
    runAction(async () => {
      await setModel(name, model);
      setModelOpen(false);
    }, "failed to change model");

  const applyContext = (tokens: number) =>
    runAction(async () => {
      await setContextWindow(name, tokens);
      setContextOpen(false);
    }, "failed to change context window");

  const handleSignOut = () =>
    runAction(async () => {
      await signOutProvider(name);
      setSignOutOpen(false);
    }, "failed to sign out");

  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div
            className={`flex size-11 shrink-0 items-center justify-center rounded-2xl [corner-shape:squircle] ${
              isOpenRouter ? "bg-muted" : "bg-[#D97757]/10"
            }`}
          >
            <Logo className="size-6" />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">
              {manifest?.providers[provider.kind]?.display ??
                (isOpenRouter ? "OpenRouter" : "Claude account")}
            </span>
            <div className="flex min-w-0 items-center gap-2">
              <span
                className="truncate text-sm font-medium"
                title={provider.model ?? "unknown"}
              >
                {provider.model ?? "unknown"}
              </span>
              <Badge variant="secondary" className="shrink-0">
                {contextLabel}
              </Badge>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              plan usage
            </span>
            <button
              onClick={refreshUsage}
              aria-label="refresh usage"
              className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <RefreshCw
                className={`size-3.5 ${usageLoading ? "animate-spin" : ""}`}
              />
            </button>
          </div>
          {usageLoading ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-8" />
              </div>
              <Skeleton className="h-1.5 w-full" />
            </div>
          ) : usageError ? (
            <p className="text-xs text-muted-foreground">
              failed to load usage data
            </p>
          ) : meters.length === 0 && !credits ? (
            <p className="text-xs text-muted-foreground">
              no usage data available
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {meters.map((m) => (
                <UsageBar key={m.label} meter={m} />
              ))}
              {credits && (
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">credits</span>
                  <span className="text-foreground tabular-nums">
                    {credits.used != null
                      ? `$${credits.used.toFixed(2)}${credits.limit != null ? ` / $${credits.limit.toFixed(2)}` : ""}`
                      : "—"}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={() => setModelOpen(true)}
          >
            change model
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={() => setContextOpen(true)}
          >
            change context
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="more actions"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => void handleOpenAuth()}>
                <ArrowLeftRight className="size-4" />
                switch provider
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() => setSignOutOpen(true)}
              >
                <LogOut className="size-4" />
                sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardContent>

      <Dialog
        open={modelOpen}
        onOpenChange={(next) => {
          if (!next) {
            setModelOpen(false);
            setError(null);
          }
        }}
      >
        <DialogContent className="gap-8 sm:max-w-[472px]" showCloseButton>
          <DialogHeader>
            <DialogTitle>change model</DialogTitle>
            <DialogDescription className="sr-only">
              pick a new model for this agent
            </DialogDescription>
          </DialogHeader>
          {applying ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <ProgressBar message="switching model, restarting agent..." />
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4 py-2">
              <ModelStep
                initialModel={provider.model ?? ""}
                models={isOpenRouter ? undefined : claudeModels}
                allowCustom={isOpenRouter}
                submitLabel="switch model"
                onSubmit={(model) => void applyModel(model)}
              />
              {error && (
                <p className="text-xs text-destructive text-center">{error}</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={contextOpen}
        onOpenChange={(next) => {
          if (!next) {
            setContextOpen(false);
            setError(null);
          }
        }}
      >
        <DialogContent className="gap-8 sm:max-w-[472px]" showCloseButton>
          <DialogHeader>
            <DialogTitle>change context window</DialogTitle>
            <DialogDescription className="sr-only">
              pick a new context window for this agent
            </DialogDescription>
          </DialogHeader>
          {applying ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <ProgressBar message="changing context window, restarting agent..." />
            </div>
          ) : !manifest ? (
            <div className="flex w-full flex-col gap-1.5 py-2">
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4 py-2">
              <ContextStep
                presets={
                  manifest.providers[provider.kind]?.context.presets ?? []
                }
                initial={
                  provider.max_context_tokens ??
                  manifest.providers[provider.kind]?.context.default ??
                  0
                }
                submitLabel="apply"
                onSubmit={(tokens) => void applyContext(tokens)}
              />
              {error && (
                <p className="text-xs text-destructive text-center">{error}</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={signOutOpen}
        onOpenChange={(next) => {
          if (!next) {
            setSignOutOpen(false);
            setError(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>sign out {name}?</AlertDialogTitle>
            <AlertDialogDescription>
              this clears its provider — credentials, model, and context window.
              {name} won't be able to respond until you reconnect a provider.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p className="text-xs text-destructive text-center">{error}</p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={applying}
              onClick={(e) => {
                e.preventDefault();
                void handleSignOut();
              }}
            >
              {applying ? "signing out..." : "sign out"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
