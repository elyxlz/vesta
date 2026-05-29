import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createAgent, startAuth, type AuthStartResult } from "@/api";
import type { OpenRouterConfig } from "@/api/agents";
import { fadeSlide } from "@/lib/motion";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { ProviderPicker } from "@/components/ProviderPicker";
import { CreatingStep } from "./Steps/CreatingStep";
import { AuthStep } from "./Steps/AuthStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { DoneStep } from "./Steps/DoneStep";

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const [agentName, setAgentName] = useState("");
  const [seedPersonality, setSeedPersonality] = useState<string | null>(null);
  const [openrouter, setOpenrouter] = useState<OpenRouterConfig | null>(null);
  const [credentials, setCredentials] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [authStartError, setAuthStartError] = useState<string | null>(null);

  useEffect(() => {
    setStep("name");
    return () => setStep(null);
  }, []);

  // Kick off the standalone OAuth session once when entering the auth step.
  // Owned by NewAgent (not AuthStep) so remounting AuthStep doesn't restart
  // a fresh PKCE session and invalidate the user's pasted code.
  useEffect(() => {
    if (step !== "auth" || authStart !== null || authStartError !== null) return;
    let cancelled = false;
    startAuth()
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

  useEffect(() => {
    if (step !== "creating" || !agentName || !seedPersonality) return;
    let cancelled = false;
    (async () => {
      try {
        await createAgent(
          agentName,
          seedPersonality,
          openrouter ?? undefined,
          credentials ?? undefined,
        );
        if (cancelled) return;
        setStep("done");
      } catch (e) {
        if (cancelled) return;
        setCreateError(
          (e as { message?: string })?.message || "creation failed",
        );
        // Reset provider-dependent state so a retry starts clean and can't
        // send both credentials and openrouter (mutually-exclusive on server).
        setCredentials(null);
        setOpenrouter(null);
        setAuthStart(null);
        setAuthStartError(null);
        setStep("name");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, agentName, seedPersonality, openrouter, credentials, setStep]);

  const content = (() => {
    if (step === "provider")
      return (
        <ProviderPicker
          onDone={(or) => {
            // Re-picking provider must invalidate the other branch's state:
            // credentials from a prior Claude attempt or vice versa.
            setOpenrouter(or);
            setCredentials(null);
            setAuthStart(null);
            setAuthStartError(null);
            setStep(or ? "personality" : "auth");
          }}
          onBack={() => setStep("name")}
        />
      );
    if (step === "auth")
      return (
        <AuthStep
          authStart={authStart}
          startError={authStartError}
          onCredentialsReady={(creds) => {
            setCredentials(creds);
            setStep("personality");
          }}
          onCancel={() => {
            setAuthStart(null);
            setAuthStartError(null);
            setStep("provider");
          }}
        />
      );
    if (step === "personality")
      return (
        <PersonalityStep
          onPicked={(name) => {
            setSeedPersonality(name);
            setStep("creating");
          }}
        />
      );
    if (step === "creating") return <CreatingStep />;
    if (step === "done") return <DoneStep agentName={agentName} />;
    return (
      <NameStep
        initialError={createError}
        onNamed={(name) => {
          setAgentName(name);
          setCreateError(null);
          setStep("provider");
        }}
      />
    );
  })();

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 flex items-center justify-center">
        <AnimatePresence mode="wait">
          <motion.div key={step} {...fadeSlide}>
            {content}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
