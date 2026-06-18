import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeftIcon } from "lucide-react";
import { stepTransition } from "@/lib/motion";
import { claudeProvider } from "@/api";
import type { ProviderResult } from "@/api/agents";

type AuthStartResult = claudeProvider.OAuthStartResult;
import { ChoiceStep } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import { ContextStep } from "./ContextStep";
import { AuthStep } from "./AuthStep";
import type { ProviderMode } from "./types";
import { useAgentDefaults } from "@/hooks/use-agent-defaults";
import { Skeleton } from "@/components/ui/skeleton";

type InternalStep = "choice" | "auth" | "key" | "model" | "context";

export function ProviderPicker({
  onDone,
  onBack,
}: {
  onDone: (result: ProviderResult) => void;
  onBack?: () => void;
}) {
  const [step, setStep] = useState<InternalStep>("choice");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authStartError, setAuthStartError] = useState<string | null>(null);
  // Creation defaults (context window + presets) come from vestad, not a local copy.
  const defaults = useAgentDefaults();

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
        setAuthStartError(
          (e as { message?: string })?.message || "failed to start auth",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [step, authStart, authStartError]);

  // Wait for vestad's defaults before rendering any step that needs the context window.
  // The user reaches this picker after the personality step, so it is loaded in practice.
  if (!defaults) {
    return (
      <div className="flex w-[380px] max-w-full flex-col items-center gap-4 px-4">
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }

  const handleChoice = (next: ProviderMode) => {
    setStep(next === "claude" ? "auth" : "key");
  };

  const handleCredentialsReady = (creds: string) => {
    onDone({
      kind: "claude",
      credentials: creds,
      model: undefined,
      maxContextTokens: defaults.context_tokens,
    });
  };

  const handleKeyNext = (newKey: string) => {
    setKey(newKey);
    setStep("model");
  };

  const handleContextSubmit = (maxContextTokens: number) => {
    onDone({
      kind: "openrouter",
      config: { key, model },
      maxContextTokens,
    });
  };

  const resetAuth = () => {
    setAuthStart(null);
    setAuthStartError(null);
  };

  const back = (() => {
    if (step === "choice") return onBack;
    if (step === "model") return () => setStep("key");
    if (step === "context") return () => setStep("model");
    // auth and key both return to the choice screen.
    return () => {
      resetAuth();
      setStep("choice");
    };
  })();

  return (
    <div className="relative flex w-[380px] max-w-full flex-col items-center gap-4 px-4">
      {back && (
        <button
          type="button"
          onClick={back}
          className="absolute top-0 left-0 -ml-1 flex size-7 items-center justify-center rounded-full text-muted-foreground transition hover:bg-input/60 hover:text-foreground"
          aria-label="back"
        >
          <ChevronLeftIcon className="size-4" />
        </button>
      )}

      <AnimatePresence mode="wait">
        <motion.div key={step} {...stepTransition} className="w-full">
          {step === "choice" && <ChoiceStep onPick={handleChoice} />}
          {step === "auth" && (
            <AuthStep
              authStart={authStart}
              startError={authStartError}
              onCredentialsReady={handleCredentialsReady}
              onCancel={() => {
                resetAuth();
                setStep("choice");
              }}
            />
          )}
          {step === "key" && (
            <KeyStep initialKey={key} onNext={handleKeyNext} />
          )}
          {step === "model" && (
            <ModelStep
              initialModel={model}
              onModelChange={setModel}
              onSubmit={(m) => {
                setModel(m);
                setStep("context");
              }}
            />
          )}
          {step === "context" && (
            <ContextStep
              presets={defaults.context_presets}
              initial={defaults.context_tokens}
              onSubmit={handleContextSubmit}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export type { ProviderMode };
