import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createAgent, authenticate, type AuthStartResult } from "@/api";
import { fadeSlide } from "@/lib/motion";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { CreatingStep } from "./Steps/CreatingStep";
import { AuthStep } from "./Steps/AuthStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { DoneStep } from "./Steps/DoneStep";

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const [agentName, setAgentName] = useState("");
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);
  const [seedPersonality, setSeedPersonality] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    setStep("name");
    return () => setStep(null);
  }, []);

  useEffect(() => {
    if (step !== "creating" || !agentName || !seedPersonality) return;
    let cancelled = false;
    (async () => {
      try {
        await createAgent(agentName, seedPersonality);
        const auth = await authenticate(agentName);
        if (cancelled) return;
        setAuthStart(auth);
        setStep("auth");
      } catch (e) {
        if (cancelled) return;
        setCreateError(
          (e as { message?: string })?.message || "creation failed",
        );
        setStep("name");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, agentName, seedPersonality, setStep]);

  const content = (() => {
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
    if (step === "auth" && authStart)
      return (
        <AuthStep
          agentName={agentName}
          authStart={authStart}
          onDone={() => setStep("done")}
        />
      );
    if (step === "done") return <DoneStep agentName={agentName} />;
    return (
      <NameStep
        initialError={createError}
        onNamed={(name) => {
          setAgentName(name);
          setCreateError(null);
          setStep("personality");
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
