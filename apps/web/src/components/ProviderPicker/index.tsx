import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeftIcon } from "lucide-react";
import { stepTransition } from "@/lib/motion";
import { claudeProvider } from "@/api";
import type { ProviderResult } from "@/api/agents";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

type AuthStartResult = claudeProvider.OAuthStartResult;
import { ChoiceStep } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import { ContextStep } from "./ContextStep";
import { AuthStep } from "./AuthStep";
import type { ProviderMode } from "./types";

type InternalStep =
  | "choice"
  | "auth"
  | "claude-model"
  | "key"
  | "model"
  | "context";

// Shown immediately; refined from vestad's /providers/claude/models on mount so a
// newly-added model appears without a code change. claude-code resolves the aliases.
const CLAUDE_FALLBACK: OpenRouterModelOption[] = [
  { slug: "opus", label: "Claude Opus", author: "Anthropic" },
  { slug: "sonnet", label: "Claude Sonnet", author: "Anthropic" },
  { slug: "haiku", label: "Claude Haiku", author: "Anthropic" },
];

export function ProviderPicker({
  onDone,
  onBack,
}: {
  onDone: (result: ProviderResult) => void;
  onBack?: () => void;
}) {
  const [step, setStep] = useState<InternalStep>("choice");
  const [mode, setMode] = useState<ProviderMode>("claude");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [claudeModel, setClaudeModel] = useState("");
  const [credentials, setCredentials] = useState("");
  const [claudeModels, setClaudeModels] =
    useState<OpenRouterModelOption[]>(CLAUDE_FALLBACK);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authStartError, setAuthStartError] = useState<string | null>(null);

  // Refine the Claude model list once; failures keep the fallback.
  useEffect(() => {
    let cancelled = false;
    claudeProvider
      .fetchModels()
      .then((items) => {
        if (cancelled || items.length === 0) return;
        setClaudeModels(
          items.map((m) => ({
            slug: m.id,
            label: m.label,
            author: "Anthropic",
          })),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

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

  const handleChoice = (next: ProviderMode) => {
    setMode(next);
    setStep(next === "claude" ? "auth" : "key");
  };

  const handleCredentialsReady = (creds: string) => {
    setCredentials(creds);
    setStep("claude-model");
  };

  const handleKeyNext = (newKey: string) => {
    setKey(newKey);
    setStep("model");
  };

  const handleContextSubmit = (maxContextTokens: number) => {
    if (mode === "claude") {
      onDone({
        kind: "claude",
        credentials,
        model: claudeModel || undefined,
        maxContextTokens,
      });
    } else {
      onDone({
        kind: "openrouter",
        config: { key, model },
        maxContextTokens,
      });
    }
  };

  const resetAuth = () => {
    setAuthStart(null);
    setAuthStartError(null);
  };

  const back = (() => {
    if (step === "choice") return onBack;
    if (step === "model") return () => setStep("key");
    if (step === "context")
      return () => setStep(mode === "claude" ? "claude-model" : "model");
    if (step === "claude-model")
      return () => {
        resetAuth();
        setStep("choice");
      };
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
          {step === "claude-model" && (
            <ModelStep
              initialModel={claudeModel}
              models={claudeModels}
              allowCustom={false}
              onModelChange={setClaudeModel}
              onSubmit={(m) => {
                setClaudeModel(m);
                setStep("context");
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
          {step === "context" && <ContextStep onSubmit={handleContextSubmit} />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export type { ProviderMode };
