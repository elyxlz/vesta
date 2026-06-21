import { useState } from "react";
import { Cpu, ArrowLeftRight, Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProgressBar } from "@/components/ProgressBar";
import { ModelStep } from "@/components/ProviderPicker/ModelStep";
import { ContextStep } from "@/components/ProviderPicker/ContextStep";
import { setModel, setContextWindow } from "@/api/agents";
import { formatTokens } from "@/lib/format";
import { errorMessage } from "@/lib/utils";
import { useProvider } from "@/hooks/use-provider";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

/// Provider hub for an agent: shows the current provider, model, and context
/// window; lets you switch between Claude and OpenRouter (reuses the reconfigure
/// modal), change the model, and change the context window — each without
/// re-entering credentials.
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

  if (!provider || provider.kind === "none") return null;

  const isOpenRouter = provider.kind === "openrouter";

  const applyModel = async (model: string) => {
    if (!name) return;
    setApplying(true);
    setError(null);
    try {
      await setModel(name, model);
      setModelOpen(false);
      refresh();
    } catch (e) {
      setError(errorMessage(e, "failed to change model"));
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
    } catch (e) {
      setError(errorMessage(e, "failed to change context window"));
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
