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
import { setModel } from "@/api/agents";
import { useProvider } from "@/hooks/use-provider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

/// Provider hub for an agent: shows the current provider + model, lets you
/// switch between Claude and OpenRouter (reuses the reconfigure modal), and —
/// for OpenRouter — change just the model without re-entering the key.
export function ProviderCard() {
  const { name } = useSelectedAgent();
  const { handleOpenAuth } = useModals();
  const { provider, refresh } = useProvider(name);
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
        {isOpenRouter && (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            change model
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => void handleOpenAuth()}>
          <ArrowLeftRight className="size-4" />
          switch provider
        </Button>
      </CardContent>

      {isOpenRouter && (
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
                pick a new OpenRouter model for this agent
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
                  onModelChange={() => {}}
                  onSubmit={(model) => void apply(model)}
                />
                {error && (
                  <p className="text-xs text-destructive text-center">{error}</p>
                )}
              </div>
            )}
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}
