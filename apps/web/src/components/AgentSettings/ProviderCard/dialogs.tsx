import { useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
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
import { Skeleton } from "@/components/ui/skeleton";
import { ProgressBar } from "@/components/ProgressBar";
import { ModelStep } from "@/components/ProviderPicker/ModelStep";
import { ContextStep } from "@/components/ProviderPicker/ContextStep";
import { planContextOptions } from "@/components/ProviderPicker/context-plan";
import { providerModelOptions } from "@/components/ProviderPicker/model-options";
import type { ProviderInfo } from "@/api/agents";
import { contextForModel, type ProviderCatalog } from "@/api/catalogs";
import {
  fetchTopModels,
  type OpenRouterModelOption,
} from "@/api/providers/openrouter";

export function ModelDialog({
  agentName,
  open,
  onClose,
  applying,
  error,
  provider,
  claudeLiveModels,
  catalog,
  onSubmit,
}: {
  agentName: string;
  open: boolean;
  onClose: () => void;
  applying: boolean;
  error: string | null;
  provider: ProviderInfo;
  claudeLiveModels: OpenRouterModelOption[] | null;
  catalog: ProviderCatalog | undefined;
  onSubmit: (model: string) => void;
}) {
  const isClaude = provider.kind === "claude";
  const configuredKind = provider.kind === "none" ? null : provider.kind;
  const loadOpenRouterModels = useCallback(
    () => fetchTopModels(agentName),
    [agentName],
  );
  const fixedModels = providerModelOptions(
    configuredKind,
    catalog,
    provider.model,
  );
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
              models={fixedModels}
              claudeLiveModels={isClaude ? claudeLiveModels : undefined}
              loadModels={
                provider.kind === "openrouter"
                  ? loadOpenRouterModels
                  : undefined
              }
              submitLabel="switch model"
              onSubmit={onSubmit}
            />
            {error && (
              <p className="text-sm text-destructive text-center">{error}</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ContextDialog({
  open,
  onClose,
  applying,
  error,
  provider,
  catalog,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  applying: boolean;
  error: string | null;
  provider: ProviderInfo;
  catalog: ProviderCatalog | undefined;
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
        ) : !catalog ? (
          <div className="flex w-full flex-col gap-1.5 py-2">
            <Skeleton className="h-12 w-full rounded-xl" />
            <Skeleton className="h-12 w-full rounded-xl" />
            <Skeleton className="h-12 w-full rounded-xl" />
          </div>
        ) : (
          <div className="flex flex-col items-center gap-4 py-2">
            {(() => {
              const context = contextForModel(
                provider.kind === "none"
                  ? undefined
                  : catalog.providers[provider.kind],
                provider.model ?? "",
              );
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
              <p className="text-sm text-destructive text-center">{error}</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function SignOutDialog({
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
          <p className="text-sm text-destructive text-center">{error}</p>
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
/// window, and plan usage; lets you switch between supported providers
/// (reuses the reconfigure modal), change the model, and change the context
/// window — each without re-entering credentials.
