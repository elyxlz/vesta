import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { type AuthStartResult } from "@/api";
import { fadeSlide } from "@/lib/motion";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { CreatingStep } from "./Steps/CreatingStep";
import { AuthStep } from "./Steps/AuthStep";
import { FinalizingStep } from "./Steps/FinalizingStep";
import { DoneStep } from "./Steps/DoneStep";

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const [agentName, setAgentName] = useState("");
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);

  useEffect(() => {
    setStep("name");
    return () => setStep(null);
  }, []);

  const content = (() => {
    if (step === "creating") return <CreatingStep />;
    if (step === "auth" && authStart)
      return (
        <AuthStep
          agentName={agentName}
          authStart={authStart}
          onDone={() => setStep("done")}
        />
      );
    if (step === "finalizing") return <FinalizingStep />;
    if (step === "done") return <DoneStep agentName={agentName} />;
    return (
      <NameStep
        onCreated={(name, auth) => {
          setAgentName(name);
          setAuthStart(auth);
          setStep("auth");
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
