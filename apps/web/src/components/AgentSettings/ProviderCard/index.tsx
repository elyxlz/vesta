import { useState } from "react";
import {
  MoreHorizontal,
  RefreshCw,
  LogOut,
  Plug,
  SlidersHorizontal,
  Unplug,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/DropdownMenu";
import { Skeleton } from "@/components/ui/skeleton";
import { providerMeta } from "@/components/ProviderPicker/providers";
import type { ProviderKind } from "@vesta/core";
import {
  setModel,
  setContextWindow,
  signOutProvider,
  type ProviderInfo,
} from "@/api/agents";
import { fetchAgentClaudeModels } from "@/api/providers/claude";
import { contextForModel, type ProviderCatalog } from "@/api/catalogs";
import { formatTokens } from "@/lib/format";
import { errorMessage } from "@/lib/utils";
import { useProvider } from "@/hooks/use-provider";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { useUsage } from "./use-usage";
import { ModelDialog, ContextDialog, SignOutDialog } from "./dialogs";
import { UsageSection } from "./usage";

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
            <span className="text-sm text-muted-foreground">provider</span>
            <span className="truncate text-base font-medium">
              not connected
            </span>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          {name} needs a provider before it can respond. connect one to get
          started.
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
  catalog,
  ready,
}: {
  provider: ProviderInfo;
  kind: ProviderKind;
  catalog: ProviderCatalog | undefined;
  ready: boolean;
}) {
  const isClaude = kind === "claude";
  const { Logo } = providerMeta(kind);
  const defaultContext = contextForModel(
    catalog?.providers[kind],
    provider.model ?? "",
  )?.default;
  const contextLabel =
    provider.max_context_tokens != null
      ? `${formatTokens(provider.max_context_tokens)} context`
      : kind === "openrouter"
        ? "model context"
        : defaultContext != null && defaultContext > 0
          ? `${formatTokens(defaultContext)} context`
          : "default context";

  return (
    <div className="flex items-center gap-3">
      <div
        className={`flex size-11 shrink-0 items-center justify-center rounded-2xl [corner-shape:squircle] ${
          isClaude ? "bg-[#D97757]/10" : "bg-muted"
        }`}
      >
        <Logo className="size-6" />
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm text-muted-foreground">
          {catalog?.providers[kind]?.display ?? kind}
        </span>
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="truncate text-base font-medium"
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

export function ProviderCard() {
  const { name, agent } = useSelectedAgent();
  const openDialog = useDialogs((s) => s.setOpen);
  // Revalidate on status change so a provider switch (which restarts the agent)
  // is reflected here without a manual reload.
  const { provider, catalog, refresh } = useProvider(name, agent.status);
  // Context-window presets come from this agent's provider catalog. The context dialog needs the
  // active provider's presets just like the setup wizard does.
  const [modelOpen, setModelOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The live Claude catalog for the change-model dialog, listed by the agent from its own
  // stored credentials while the card shows Claude, so the dialog opens ready.
  const claudeLiveModels = useClaudeModels(
    provider?.kind === "claude" && name ? name : null,
    fetchAgentClaudeModels,
  );

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
    return (
      <NotConnectedCard
        name={name}
        onSetup={() => openDialog("providerAuth", true)}
      />
    );
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
      <CardHeader>
        <CardTitle>
          <Plug className="size-4 text-muted-foreground" />
          provider
        </CardTitle>
        <CardDescription>
          the model {name} runs on, plus your plan usage and account.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ProviderIdentity
          provider={provider}
          kind={provider.kind}
          catalog={catalog}
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
          <p className="text-sm text-muted-foreground">
            {name}&apos;s credentials expired or were rejected. sign in again to
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
                onClick={() => openDialog("providerAuth", true)}
              >
                change provider
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => setModelOpen(true)}
              >
                change model
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              className="flex-1"
              onClick={() => openDialog("providerAuth", true)}
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
              {ready && provider.kind !== "openrouter" && (
                <DropdownMenuItem onClick={() => setContextOpen(true)}>
                  <SlidersHorizontal className="size-4" />
                  change context
                </DropdownMenuItem>
              )}
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
        agentName={name}
        open={modelOpen}
        onClose={() => {
          setModelOpen(false);
          setError(null);
        }}
        applying={applying}
        error={error}
        provider={provider}
        claudeLiveModels={claudeLiveModels}
        catalog={catalog}
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
        catalog={catalog}
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
