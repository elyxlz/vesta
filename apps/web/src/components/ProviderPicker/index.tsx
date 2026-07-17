import { useEffect, useState } from "react";
import { ChevronLeftIcon } from "lucide-react";
import { claudeProvider } from "@/api";
import type { ProviderResult } from "@/api/agents";

type AuthStartResult = claudeProvider.OAuthStartResult;
import { ChoiceStep } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import { ContextStep } from "./ContextStep";
import { planContextOptions, planFromCredentials } from "./context-plan";
import { AuthStep } from "./AuthStep";
import { ClaudeLogo, OpenRouterLogo } from "./logos";
import type { ProviderMode } from "./types";
import { useManifest } from "@/hooks/use-manifest";
import { useClaudeModels } from "@/hooks/use-claude-models";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, errorMessage } from "@/lib/utils";

type InternalStep = "choice" | "auth" | "key" | "model" | "context";

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

  // Kick off the standalone OAuth session once when entering the auth substep.
  // Owned here (not by AuthStep) so AuthStep remounts don't restart a fresh
  // PKCE session and invalidate any code the user already pasted.
  useEffect(() => {
    if (step !== "auth" || authStart !== null || authStartError !== null)
      return;
    let cancelled = false;
    claudeProvider
      .startOAuth()
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
  }, [step, authStart, authStartError]);

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
    // Claude authenticates first; OpenRouter takes a key first. Both then walk
    // the shared model -> context steps.
    setStep(next === "claude" ? "auth" : "key");
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
    const context = manifest.providers[provider]?.context;
    const plan =
      provider === "claude" && creds !== null
        ? planFromCredentials(creds)
        : null;
    const { initial } = context
      ? planContextOptions(context, plan)
      : { initial: 0 };
    const defaultModel = manifest.providers[provider]?.default_model ?? "";
    if (provider === "claude") {
      if (creds === null) return;
      onDone({
        kind: "claude",
        credentials: creds,
        model: defaultModel || undefined,
        maxContextTokens: initial,
      });
      return;
    }
    onDone({
      kind: "openrouter",
      config: { key: apiKey, model: defaultModel },
      maxContextTokens: initial,
    });
  };

  const handleContextSubmit = (maxContextTokens: number) => {
    if (provider === "claude") {
      if (credentials === null) return;
      onDone({
        kind: "claude",
        credentials,
        model: model || undefined,
        maxContextTokens,
      });
      return;
    }
    onDone({ kind: "openrouter", config: { key, model }, maxContextTokens });
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
      return () => setStep(provider === "claude" ? "auth" : "key");
    if (step === "context") return () => setStep("model");
    // auth and key both return to the choice screen.
    return cancelToChoice;
  })();

  const stepLogo = provider === "claude" ? <ClaudeLogo /> : <OpenRouterLogo />;

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
          <AuthStep
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
            logo={<OpenRouterLogo />}
            onCancel={cancelToChoice}
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
              setStep("context");
            }}
            models={provider === "claude" ? claudeModels : undefined}
            allowCustom={provider !== "claude"}
            logo={stepLogo}
            onCancel={cancelToChoice}
          />
        )}
        {step === "context" &&
          provider &&
          (() => {
            const context = manifest.providers[provider]?.context;
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
