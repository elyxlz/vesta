import {
  type AuthStartResult,
  providerResult,
  modelStepInitialModel,
  providerUsesOAuth,
  catalogIsLive,
  startProviderOAuth,
  keyStepCopy,
} from "./provider-flow";
import {
  ClaudeLogo,
  KimiLogo,
  OpenAILogo,
  OpenRouterLogo,
  ZaiLogo,
} from "./logos";
import { useCallback, useEffect, useState } from "react";
import { claudeProvider, openrouterProvider } from "@/api";
import type { ProviderResult } from "@/api/agents";
import { ChoiceStep, type ChoiceVariant } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import { ContextStep } from "./ContextStep";
import { planContextOptions, planFromCredentials } from "./context-plan";
import type { ProviderKind } from "@vesta/core";
import { useProviderCatalog } from "@/hooks/use-agent-catalogs";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn, errorMessage } from "@/lib/utils";
import { contextForModel } from "@/api/catalogs";
import { providerModelOptions } from "./model-options";
import { ProviderAuthStep } from "./auth-step";

function providerLogo(provider: ProviderKind | null) {
  if (provider === "claude") return <ClaudeLogo />;
  if (provider === "zai") return <ZaiLogo />;
  if (provider === "kimi") return <KimiLogo />;
  if (provider === "openai") return <OpenAILogo />;
  return <OpenRouterLogo />;
}

type InternalStep = "choice" | "auth" | "key" | "model" | "context";

export function ProviderPicker({
  agentName,
  onDone,
  onBack,
  className,
  defaultsOnly,
  choiceVariant,
}: {
  agentName: string;
  onDone: (result: ProviderResult) => void;
  onBack?: () => void;
  className?: string;
  // Onboarding mode: every provider walks the model step, but a fixed-catalog
  // provider finishes right after with the default context for the chosen model
  // instead of walking ContextStep. Context stays editable afterward in
  // AgentSettings' full picker.
  defaultsOnly?: boolean;
  // The provider chooser's layout: "grid" is the onboarding glass-tile look,
  // undefined keeps the compact settings look.
  choiceVariant?: ChoiceVariant;
}) {
  const [step, setStep] = useState<InternalStep>("choice");
  // The chosen provider drives the shared model/context steps (which list to
  // show, which logo, and how the final result is shaped).
  const [provider, setProvider] = useState<ProviderKind | null>(null);
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [credentials, setCredentials] = useState<string | null>(null);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authStartError, setAuthStartError] = useState<string | null>(null);
  // The live Claude catalog, fetched as soon as auth stashes the credentials so
  // it is ready by the time the model step renders.
  const fetchClaudeModels = useCallback(
    (nextCredentials: string) =>
      claudeProvider.fetchClaudeModels(agentName, nextCredentials),
    [agentName],
  );
  const fetchOpenRouterModels = useCallback(
    () => openrouterProvider.fetchTopModels(agentName),
    [agentName],
  );
  const validateOpenRouterKey = useCallback(
    (nextKey: string) => openrouterProvider.validateKey(agentName, nextKey),
    [agentName],
  );
  const claudeLiveModels = useClaudeModels(
    provider === "claude" ? credentials : null,
    fetchClaudeModels,
  );
  const {
    data: catalog,
    error: catalogError,
    retry: retryCatalog,
  } = useProviderCatalog(agentName);
  const providerModels = providerModelOptions(provider, catalog);
  const stepLogo = providerLogo(provider);
  const keyCopy = keyStepCopy(provider);

  // Kick off this agent's OAuth session once when entering the auth substep.
  // Owned here (not by AuthStep) so AuthStep remounts don't restart a fresh
  // PKCE session and invalidate any code the user already pasted.
  useEffect(() => {
    if (step !== "auth" || authStart !== null || authStartError !== null)
      return;
    let cancelled = false;
    startProviderOAuth(agentName, provider)
      .then((res) => {
        if (!cancelled) setAuthStart(res);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setAuthStartError(errorMessage(e, "failed to start auth"));
      });
    return () => {
      cancelled = true;
    };
  }, [step, provider, authStart, authStartError, agentName]);

  if (catalogError) {
    return (
      <div className="flex w-[380px] max-w-full flex-col items-center gap-3 px-4 text-center">
        <p className="text-xs text-destructive">{catalogError}</p>
        <Button type="button" variant="outline" onClick={retryCatalog}>
          retry
        </Button>
      </div>
    );
  }

  // Wait for the catalog before rendering any step that needs the context window.
  // The user reaches this picker after the personality step, so it is loaded in practice.
  if (!catalog) {
    return (
      <div
        className={cn(
          "flex w-[380px] max-w-full flex-col items-start gap-4 px-4",
          className,
        )}
      >
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }

  const handleChoice = (next: ProviderKind) => {
    resetAuth();
    setCredentials(null);
    setKey("");
    setModel("");
    setProvider(next);
    // Claude authenticates first; key-backed providers take a key first. All then walk
    // the shared model -> context steps.
    setStep(providerUsesOAuth(next, catalog) ? "auth" : "key");
  };

  // Claude auth no longer ends the flow: stash the credentials and continue to
  // the model step, mirroring the OpenRouter path. Every provider now picks a
  // model, a fixed-catalog one from the catalog list.
  const handleCredentialsReady = (creds: string) => {
    setCredentials(creds);
    setStep("model");
  };

  const handleKeyNext = (newKey: string) => {
    setKey(newKey);
    setStep("model");
  };

  // Onboarding (defaultsOnly) finishes a fixed-catalog provider right after the
  // model step, taking the default context window for the chosen model instead
  // of walking ContextStep. Context stays editable later in AgentSettings.
  const finishWithModel = (selectedModel: string) => {
    if (provider === null) return;
    const context = contextForModel(catalog.providers[provider], selectedModel);
    const { initial } = context
      ? planContextOptions(context, null)
      : { initial: 0 };
    const result = providerResult(
      provider,
      credentials,
      key,
      selectedModel,
      initial,
    );
    if (result) onDone(result);
  };

  const handleContextSubmit = (maxContextTokens: number) => {
    if (provider === null) return;
    const result = providerResult(
      provider,
      credentials,
      key,
      model,
      maxContextTokens,
    );
    if (result) onDone(result);
  };

  const resetAuth = () => {
    setAuthStart(null);
    setAuthStartError(null);
  };

  // Abandon the chosen provider and return to the choice screen. Auth and key
  // back out here; model and context step back one screen without resetting.
  const cancelToChoice = () => {
    resetAuth();
    setCredentials(null);
    setKey("");
    setModel("");
    setProvider(null);
    setStep("choice");
  };

  // The model step's previous screen depends on how the provider started.
  const backFromModel = () =>
    setStep(providerUsesOAuth(provider, catalog) ? "auth" : "key");

  // The grid choice step is as wide as the onboarding vibe grid; every other
  // step keeps the compact column.
  const gridChoice = step === "choice" && choiceVariant === "grid";
  return (
    <div
      className={cn(
        "flex max-w-full flex-col items-start gap-4 px-4",
        gridChoice ? "w-[560px]" : "w-[380px]",
        className,
      )}
    >
      <div className="w-full">
        {step === "choice" && (
          <ChoiceStep
            onPick={handleChoice}
            catalog={catalog}
            variant={choiceVariant}
            onBack={onBack}
          />
        )}
        {step === "auth" && (
          <ProviderAuthStep
            agentName={agentName}
            provider={provider}
            authStart={authStart}
            startError={authStartError}
            onCredentialsReady={handleCredentialsReady}
            onBack={cancelToChoice}
          />
        )}
        {step === "key" && (
          <KeyStep
            initialKey={key}
            onNext={handleKeyNext}
            logo={stepLogo}
            onBack={cancelToChoice}
            title={keyCopy.title}
            subtitle={keyCopy.subtitle}
            placeholder={keyCopy.placeholder}
            validateKey={
              provider === "openrouter" ? validateOpenRouterKey : undefined
            }
          />
        )}
        {step === "model" && (
          <ModelStep
            initialModel={modelStepInitialModel(provider, model, catalog)}
            onModelChange={setModel}
            onSubmit={(m) => {
              setModel(m);
              if (provider === "openrouter") {
                onDone({ kind: "openrouter", key, model: m });
              } else if (defaultsOnly && !catalogIsLive(provider, catalog)) {
                finishWithModel(m);
              } else {
                setStep("context");
              }
            }}
            models={providerModels}
            claudeLiveModels={
              provider === "claude" ? claudeLiveModels : undefined
            }
            loadModels={
              provider === "openrouter" ? fetchOpenRouterModels : undefined
            }
            logo={stepLogo}
            onBack={backFromModel}
          />
        )}
        {step === "context" &&
          provider &&
          (() => {
            const selectedModel =
              model || (catalog.providers[provider]?.default_model ?? "");
            const context = contextForModel(
              catalog.providers[provider],
              selectedModel,
            );
            // Claude gates >200K windows on the plan tier, read from the stashed OAuth blob.
            const plan =
              provider === "claude" && credentials !== null
                ? planFromCredentials(credentials)
                : null;
            const { presets, initial } = context
              ? planContextOptions(context, plan)
              : { presets: [], initial: 0 };
            return (
              <ContextStep
                presets={presets}
                initial={initial}
                onSubmit={handleContextSubmit}
                logo={stepLogo}
                onBack={() => setStep("model")}
              />
            );
          })()}
      </div>
    </div>
  );
}
