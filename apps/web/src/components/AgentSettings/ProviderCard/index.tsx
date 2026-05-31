import { useState } from "react";
import { Cpu, ArrowLeftRight } from "lucide-react";
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
import type { openrouterProvider } from "@/api";
import { setModel } from "@/api/agents";
import { useProvider } from "@/hooks/use-provider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

// Claude OAuth exposes a small fixed set; the SDK takes these short aliases.
const CLAUDE_MODELS: openrouterProvider.OpenRouterModelOption[] = [
  { slug: "opus", label: "Claude Opus", author: "Anthropic", context_length: 200000 },
  { slug: "sonnet", label: "Claude Sonnet", author: "Anthropic", context_length: 200000 },
  { slug: "haiku", label: "Claude Haiku", author: "Anthropic", context_length: 200000 },
];

/// Provider hub for an agent: shows the current provider + model, lets you
/// switch between Claude and OpenRouter (reuses the reconfigure modal), and —
/// for OpenRouter — change just the model without re-entering the key.
export function ProviderCard() {
  const { name, agent } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  // Revalidate on status change so a provider switch (which restarts the agent)
  // is reflected here without a manual reload.
  const { provider, refresh } = useProvider(name, agent?.status);
  const [open, setOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!provider || provider.kind === "none") return null;

  const isOpenRouter = provider.kind === "openrouter";

  const apply = async (model: string) => {
    if (!name) return;
    setApplying(true);
    setError(null);
    try {
      await setModel(name, model);
      setOpen(false);
      refresh();
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "failed to change model");
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
          <span className="text-sm break-all">{provider.model ?? "unknown"}</span>
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          change model
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void handleOpenAuth()}>
          <ArrowLeftRight className="size-4" />
          switch provider
        </Button>
      </CardContent>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            setOpen(false);
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
                models={isOpenRouter ? undefined : CLAUDE_MODELS}
                allowCustom={isOpenRouter}
                submitLabel="switch model"
                onSubmit={(model) => void apply(model)}
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
