import { useState } from "react";
import { Cpu, ArrowLeftRight, Gauge, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ProgressBar } from "@/components/ProgressBar";
import { ModelStep } from "@/components/ProviderPicker/ModelStep";
import { ContextStep } from "@/components/ProviderPicker/ContextStep";
import { setModel, setContextWindow, type UsageMeter } from "@/api/agents";
import { formatTokens } from "@/lib/format";
import { useProvider } from "@/hooks/use-provider";
import { useClaudeModels } from "./use-claude-models";
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
  const [modelOpen, setModelOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
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

  const meters = usage?.meters ?? [];
  const credits = usage?.credits ?? null;

  const applyModel = async (model: string) => {
    if (!name) return;
    setApplying(true);
    setError(null);
    try {
      await setModel(name, model);
      setModelOpen(false);
      refresh();
    } catch (e: unknown) {
      setError(
        (e as { message?: string })?.message || "failed to change model",
      );
    } finally {
      setApplying(false);
    }
  };

  const applyContext = async (tokens: number) => {
    if (!name) return;
    setApplying(true);
    setError(null);
    try {
      await setContextWindow(name, tokens);
      setContextOpen(false);
      refresh();
    } catch (e: unknown) {
      setError(
        (e as { message?: string })?.message ||
          "failed to change context window",
      );
    } finally {
      setApplying(false);
    }
  };

  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Cpu className="size-4" /> provider
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">
            {isOpenRouter ? "OpenRouter" : "Claude account"}
          </span>
          <span className="text-sm break-all">
            {provider.model ?? "unknown"}
          </span>
          <span className="text-xs text-muted-foreground">
            context window:{" "}
            {provider.max_context_tokens != null
              ? formatTokens(provider.max_context_tokens)
              : isOpenRouter
                ? "default"
                : "1M (default)"}
          </span>
        </div>

        <div className="flex flex-col gap-2.5 border-t border-border pt-3">
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

        <Button variant="outline" size="sm" onClick={() => setModelOpen(true)}>
          change model
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setContextOpen(true)}
        >
          <Gauge className="size-4" />
          change context window
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void handleOpenAuth()}>
          <ArrowLeftRight className="size-4" />
          switch provider
        </Button>
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
        <DialogContent className="sm:max-w-lg" showCloseButton>
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
            <div className="flex flex-col items-center gap-3 py-2">
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
        <DialogContent className="sm:max-w-lg" showCloseButton>
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
          ) : (
            <div className="flex flex-col items-center gap-3 py-2">
              <ContextStep
                initial={provider.max_context_tokens ?? undefined}
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
    </Card>
  );
}
