import { useEffect, useState } from "react";
import { ChevronLeftIcon } from "lucide-react";
import { claudeProvider, openaiProvider, openrouterProvider } from "@/api";
import type { ProviderResult } from "@/api/agents";

type AuthStartResult =
  claudeProvider.OAuthStartResult | openaiProvider.OAuthStartResult;
import { ChoiceStep } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import { ContextStep } from "./ContextStep";
import { planContextOptions, planFromCredentials } from "./context-plan";
import { AuthStep } from "./AuthStep";
import { OpenAIAuthStep } from "./OpenAIAuthStep";
import {
  ClaudeLogo,
  KimiLogo,
  OpenAILogo,
  OpenRouterLogo,
  ZaiLogo,
} from "./logos";
import type { ProviderMode } from "./types";
import { useManifest } from "@/hooks/use-manifest";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, errorMessage } from "@/lib/utils";
import { contextForModel, type Manifest } from "@/api/manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

type InternalStep = "choice" | "auth" | "key" | "model" | "context";

const KEY_STEP_COPY = {
  openrouter: {
    title: "OpenRouter API key",
    subtitle: "paste a key from openrouter.ai/keys. it stays on this machine.",
    placeholder: "sk-or-v1-...",
  },
  zai: {
    title: "Z.AI subscription key",
    subtitle:
      "paste your Coding Plan subscription key. it stays on this machine.",
    placeholder: "Z.AI subscription key",
  },
  kimi: {
    title: "Kimi Code subscription key",
    subtitle: "paste your Kimi membership key. it stays on this machine.",
    placeholder: "Kimi Code subscription key",
  },
} as const;

function modelOptions(
  provider: ProviderMode | null,
  manifest: Manifest | undefined,
  claudeModels: OpenRouterModelOption[],
): OpenRouterModelOption[] | undefined {
  if (provider === "claude") return claudeModels;
  if (provider === null || provider === "openrouter") return undefined;
  const catalog = manifest?.providers[provider]?.models;
  if (!Array.isArray(catalog)) return undefined;
  return catalog.map((slug) => ({
    slug,
    label: slug.toUpperCase(),
    author:
      provider === "kimi" ? "Kimi" : provider === "openai" ? "OpenAI" : "Z.AI",
  }));
}

function providerLogo(provider: ProviderMode | null) {
  if (provider === "claude") return <ClaudeLogo />;
  if (provider === "zai") return <ZaiLogo />;
  if (provider === "kimi") return <KimiLogo />;
  if (provider === "openai") return <OpenAILogo />;
  return <OpenRouterLogo />;
}

function keyStepCopy(provider: ProviderMode | null) {
  if (provider === "claude" || provider === "openai" || provider === null)
    return KEY_STEP_COPY.openrouter;
  return KEY_STEP_COPY[provider];
}

function providerResult(
  provider: ProviderMode,
  credentials: string | null,
  key: string,
  model: string,
  maxContextTokens: number,
): ProviderResult | null {
  if (provider === "claude") {
    return credentials === null
      ? null
      : {
          kind: "claude",
          credentials,
          model: model || undefined,
          maxContextTokens,
        };
  }
  if (provider === "openai") {
    return credentials === null
      ? null
      : {
          kind: "openai",
          credentials,
          model,
          ...(maxContextTokens > 0 ? { maxContextTokens } : {}),
        };
  }
  return {
    kind: provider,
    config: { key, model },
    ...(maxContextTokens > 0 ? { maxContextTokens } : {}),
  };
}

function isOAuthProvider(
  provider: ProviderMode | null,
): provider is "claude" | "openai" {
  return provider === "claude" || provider === "openai";
}

function startProviderOAuth(provider: ProviderMode | null) {
  return provider === "openai"
    ? openaiProvider.startOAuth()
    : claudeProvider.startOAuth();
}

function ProviderAuthStep({
  provider,
  authStart,
  startError,
  onCredentialsReady,
  onCancel,
}: {
  provider: ProviderMode | null;
  authStart: AuthStartResult | null;
  startError: string | null;
  onCredentialsReady: (credentials: string) => void;
  onCancel: () => void;
}) {
  if (provider === "claude") {
    return (
      <AuthStep
        authStart={authStart}
        startError={startError}
        onCredentialsReady={onCredentialsReady}
        onCancel={onCancel}
      />
    );
  }
  if (provider === "openai") {
    return (
      <OpenAIAuthStep
        authStart={authStart as openaiProvider.OAuthStartResult | null}
        startError={startError}
        onCredentialsReady={onCredentialsReady}
        onCancel={onCancel}
      />
    );
  }
  return null;
}

export function ProviderPicker({
  onDone,
  onBack,
  className,
  defaultsOnly,
}: {
  onDone: (result: ProviderResult) => void;
  onBack?: () => void;
  className?: string;
  // Skip ModelStep/ContextStep and finish with the manifest's default model
  // and context window as soon as credentials/key land. Onboarding uses this;
  // both values stay editable afterward in AgentSettings' full picker.
  defaultsOnly?: boolean;
}) {
  const [step, setStep] = useState<InternalStep>("choice");
  // The chosen provider drives the shared model/context steps (which list to
  // show, which logo, and how the final result is shaped).
  const [provider, setProvider] = useState<ProviderMode | null>(null);
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [credentials, setCredentials] = useState<string | null>(null);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authStartError, setAuthStartError] = useState<string | null>(null);
  // Creation catalog (per-provider context window + presets) comes from the manifest, not a local copy.
  const manifest = useManifest();
  // Claude's fixed model list; fetched only while on the Claude path.
  const claudeModels = useClaudeModels(provider === "claude");
  const providerModels = modelOptions(provider, manifest, claudeModels);
  const stepLogo = providerLogo(provider);
  const keyCopy = keyStepCopy(provider);

  // Kick off the standalone OAuth session once when entering the auth substep.
  // Owned here (not by AuthStep) so AuthStep remounts don't restart a fresh
  // PKCE session and invalidate any code the user already pasted.
  useEffect(() => {
    if (step !== "auth" || authStart !== null || authStartError !== null)
      return;
    let cancelled = false;
    startProviderOAuth(provider)
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
  }, [step, provider, authStart, authStartError]);

  // Wait for the manifest before rendering any step that needs the context window.
  // The user reaches this picker after the personality step, so it is loaded in practice.
  if (!manifest) {
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

  const handleChoice = (next: ProviderMode) => {
    setProvider(next);
    // Claude authenticates first; key-backed providers take a key first. All then walk
    // the shared model -> context steps.
    setStep(isOAuthProvider(next) ? "auth" : "key");
  };

  // Claude auth no longer ends the flow: stash the credentials and continue to
  // model + context, mirroring the OpenRouter path.
  const handleCredentialsReady = (creds: string) => {
    setCredentials(creds);
    if (defaultsOnly) {
      finishWithDefaults(creds, key);
      return;
    }
    setStep("model");
  };

  const handleKeyNext = (newKey: string) => {
    setKey(newKey);
    if (defaultsOnly) {
      finishWithDefaults(credentials, newKey);
      return;
    }
    setStep("model");
  };

  // Onboarding skips ModelStep/ContextStep entirely: finish with the
  // manifest's default model and context window as soon as the provider is
  // ready, mirroring handleContextSubmit's result shape.
  const finishWithDefaults = (creds: string | null, apiKey: string) => {
    if (provider === null) return;
    const defaultModel = manifest.providers[provider]?.default_model ?? "";
    const context = contextForModel(manifest.providers[provider], defaultModel);
    const plan =
      provider === "claude" && creds !== null
        ? planFromCredentials(creds)
        : null;
    const { initial } = context
      ? planContextOptions(context, plan)
      : { initial: 0 };
    const result = providerResult(
      provider,
      creds,
      apiKey,
      defaultModel,
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

  // Cancel abandons the chosen provider and returns to the choice screen,
  // distinct from the back-chevron which steps back one screen at a time.
  const cancelToChoice = () => {
    resetAuth();
    setCredentials(null);
    setProvider(null);
    setStep("choice");
  };

  const back = (() => {
    if (step === "choice") return onBack;
    // The model step's previous screen depends on how the provider started.
    if (step === "model")
      return () => setStep(isOAuthProvider(provider) ? "auth" : "key");
    if (step === "context") return () => setStep("model");
    // auth and key both return to the choice screen.
    return cancelToChoice;
  })();

  return (
    <div
      className={cn(
        "relative flex w-[380px] max-w-full flex-col items-start gap-4 px-4",
        className,
      )}
    >
      {back && (
        <button
          type="button"
          onClick={back}
          className="absolute top-0 left-0 -ml-1 flex size-6 items-center justify-center rounded-full text-muted-foreground transition hover:bg-input/60 hover:text-foreground"
          aria-label="back"
        >
          <ChevronLeftIcon className="size-4" />
        </button>
      )}

      <div className="w-full">
        {step === "choice" && (
          <ChoiceStep onPick={handleChoice} manifest={manifest} />
        )}
        {step === "auth" && (
          <ProviderAuthStep
            provider={provider}
            authStart={authStart}
            startError={authStartError}
            onCredentialsReady={handleCredentialsReady}
            onCancel={cancelToChoice}
          />
        )}
        {step === "key" && (
          <KeyStep
            initialKey={key}
            onNext={handleKeyNext}
            logo={stepLogo}
            onCancel={cancelToChoice}
            title={keyCopy.title}
            subtitle={keyCopy.subtitle}
            placeholder={keyCopy.placeholder}
            validateKey={
              provider === "openrouter"
                ? openrouterProvider.validateKey
                : undefined
            }
          />
        )}
        {step === "model" && (
          <ModelStep
            initialModel={
              model ||
              (provider
                ? (manifest.providers[provider]?.default_model ?? "")
                : "")
            }
            onModelChange={setModel}
            onSubmit={(m) => {
              setModel(m);
              if (provider === "openrouter") {
                onDone({ kind: "openrouter", config: { key, model: m } });
              } else {
                setStep("context");
              }
            }}
            models={provider === "openrouter" ? undefined : providerModels}
            allowCustom={provider === "openrouter"}
            logo={stepLogo}
            onCancel={cancelToChoice}
          />
        )}
        {step === "context" &&
          provider &&
          (() => {
            const selectedModel =
              model || (manifest.providers[provider]?.default_model ?? "");
            const context = contextForModel(
              manifest.providers[provider],
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
                onCancel={cancelToChoice}
              />
            );
          })()}
      </div>
    </div>
  );
}

export type { ProviderMode };
