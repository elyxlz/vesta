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
import { AuthStep } from "./AuthStep";
import type { ProviderMode } from "./types";

type InternalStep = "choice" | "auth" | "key" | "model";

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

  const handleChoice = (mode: ProviderMode) => {
    if (mode === "claude") {
      setStep("auth");
      return;
    }
    setStep("key");
  };

  const handleKeyNext = (newKey: string) => {
    setKey(newKey);
    setStep("model");
  };

  const handleModelSubmit = (newModel: string) => {
    onDone({ kind: "openrouter", config: { key, model: newModel } });
  };

  const handleCredentialsReady = (credentials: string) => {
    onDone({ kind: "claude", credentials });
  };

  const back = (() => {
    if (step === "choice") return onBack;
    if (step === "model") return () => setStep("key");
    // auth and key both return to the choice screen.
    return () => {
      setAuthStart(null);
      setAuthStartError(null);
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
                setAuthStart(null);
                setAuthStartError(null);
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
              onSubmit={handleModelSubmit}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export type { ProviderMode };
