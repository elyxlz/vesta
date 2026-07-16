import { useState } from "react";
import {
  ArrowLeftRight,
  MoreHorizontal,
  RefreshCw,
  LogOut,
  Plug,
  Unplug,
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
import { planContextOptions } from "@/components/ProviderPicker/context-plan";
import { providerMeta } from "@/components/ProviderPicker/providers";
import type { ProviderMode } from "@/components/ProviderPicker/types";
import {
  setModel,
  setContextWindow,
  signOutProvider,
  type ProviderInfo,
  type Usage,
  type UsageMeter,
} from "@/api/agents";
import type { Manifest } from "@/api/manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";
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
  if (hours > 0) return `in ${String(hours)}h ${String(mins)}m`;
  return `in ${String(mins)}m`;
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

function LoadingCard() {
  return (
    <Card size="sm">
      <CardContent className="flex items-center gap-3">
        <Skeleton className="size-11 shrink-0 rounded-2xl" />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-4 w-32" />
        </div>
      </CardContent>
    </Card>
  );
}

// Unprovisioned: no provider chosen yet (fresh agent, or signed out). Offer to connect one.
function NotConnectedCard({
  name,
  onSetup,
}: {
  name: string;
  onSetup: () => void;
}) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-muted [corner-shape:squircle]">
            <Unplug className="size-6 text-muted-foreground" />
          </div>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">provider</span>
            <span className="truncate text-sm font-medium">not connected</span>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          {name} needs a provider before it can respond. Connect Claude or
          OpenRouter to get started.
        </p>
        <Button size="sm" className="self-start" onClick={onSetup}>
          <Plug className="size-4" />
          set up provider
        </Button>
      </CardContent>
    </Card>
  );
}

// The header row: provider logo, display name, active model, and context badge.
// `kind` is the chosen provider ("none" is handled by NotConnectedCard).
function ProviderIdentity({
  provider,
  kind,
  manifest,
  ready,
}: {
  provider: ProviderInfo;
  kind: ProviderMode;
  manifest: Manifest | undefined;
  ready: boolean;
}) {
  const isOpenRouter = kind === "openrouter";
  const { Logo } = providerMeta(kind);
  const contextLabel =
    provider.max_context_tokens != null
      ? `${formatTokens(provider.max_context_tokens)} context`
      : isOpenRouter
        ? "default context"
        : "1M context";

  return (
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
          {manifest?.providers[kind]?.display ??
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
            {ready ? contextLabel : "signed out"}
          </Badge>
        </div>
      </div>
    </div>
  );
}

function UsageSection({
  usage,
  loading,
  error,
  onRefresh,
}: {
  usage: Usage | null;
  loading: boolean;
  error: boolean;
  onRefresh: () => void;
}) {
  const meters = usage?.meters ?? [];
  const credits = usage?.credits ?? null;

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          plan usage
        </span>
        <button
          onClick={onRefresh}
          aria-label="refresh usage"
          className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
      {loading ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-8" />
          </div>
          <Skeleton className="h-1.5 w-full" />
        </div>
      ) : error ? (
        <p className="text-xs text-muted-foreground">
          failed to load usage data
        </p>
      ) : meters.length === 0 && !credits ? (
        <p className="text-xs text-muted-foreground">no usage data available</p>
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
  );
}

function ModelDialog({
  open,
  onClose,
  applying,
  error,
  provider,
  claudeModels,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  applying: boolean;
  error: string | null;
  provider: ProviderInfo;
  claudeModels: OpenRouterModelOption[];
  onSubmit: (model: string) => void;
}) {
  const isOpenRouter = provider.kind === "openrouter";
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
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
              onSubmit={onSubmit}
            />
            {error && (
              <p className="text-xs text-destructive text-center">{error}</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ContextDialog({
  open,
  onClose,
  applying,
  error,
  provider,
  manifest,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  applying: boolean;
  error: string | null;
  provider: ProviderInfo;
  manifest: Manifest | undefined;
  onSubmit: (tokens: number) => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
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
            {(() => {
              const context = manifest.providers[provider.kind]?.context;
              const { presets, initial } = context
                ? planContextOptions(context, provider.plan)
                : { presets: [], initial: 0 };
              return (
                <ContextStep
                  presets={presets}
                  initial={provider.max_context_tokens ?? initial}
                  submitLabel="apply"
                  onSubmit={onSubmit}
                />
              );
            })()}
            {error && (
              <p className="text-xs text-destructive text-center">{error}</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function SignOutDialog({
  open,
  onClose,
  applying,
  error,
  name,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  applying: boolean;
  error: string | null;
  name: string;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>sign out {name}?</AlertDialogTitle>
          <AlertDialogDescription>
            this disconnects {name}'s provider and {name} won't be able to
            respond until you connect a provider again.
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
              onConfirm();
            }}
          >
            {applying ? "signing out..." : "sign out"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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
  const { provider, refresh } = useProvider(name, agent.status);
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

  // The card always renders; its content reflects the provider state. While the first fetch is in
  // flight, show a skeleton rather than collapsing the layout.
  if (!provider) return <LoadingCard />;

  if (provider.kind === "none") {
    return <NotConnectedCard name={name} onSetup={() => handleOpenAuth()} />;
  }

  // From here a provider IS chosen. `ready` means its credential is valid; otherwise the card shows a
  // re-authenticate state (credential expired/rejected) instead of model/usage controls.
  const ready = provider.authed;

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
        <ProviderIdentity
          provider={provider}
          kind={provider.kind}
          manifest={manifest}
          ready={ready}
        />

        {ready ? (
          <UsageSection
            usage={usage}
            loading={usageLoading}
            error={usageError}
            onRefresh={refreshUsage}
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            {name}&apos;s credentials expired or were rejected. Sign in again to
            reconnect.
          </p>
        )}

        <div className="flex items-center gap-2">
          {ready ? (
            <>
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
            </>
          ) : (
            <Button
              size="sm"
              className="flex-1"
              onClick={() => handleOpenAuth()}
            >
              <RefreshCw className="size-4" />
              sign in again
            </Button>
          )}
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
              <DropdownMenuItem onClick={() => handleOpenAuth()}>
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

      <ModelDialog
        open={modelOpen}
        onClose={() => {
          setModelOpen(false);
          setError(null);
        }}
        applying={applying}
        error={error}
        provider={provider}
        claudeModels={claudeModels}
        onSubmit={(model) => void applyModel(model)}
      />

      <ContextDialog
        open={contextOpen}
        onClose={() => {
          setContextOpen(false);
          setError(null);
        }}
        applying={applying}
        error={error}
        provider={provider}
        manifest={manifest}
        onSubmit={(tokens) => void applyContext(tokens)}
      />

      <SignOutDialog
        open={signOutOpen}
        onClose={() => {
          setSignOutOpen(false);
          setError(null);
        }}
        applying={applying}
        error={error}
        name={name}
        onConfirm={() => void handleSignOut()}
      />
    </Card>
  );
}
