import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createAgent } from "@/api";
import {
  setProvider,
  waitUntilRunning,
  waitUntilAlive,
  type ProviderResult,
} from "@/api/agents";
import { stepTransition } from "@/lib/motion";
import { errorMessage } from "@/lib/utils";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { ProviderPicker } from "@/components/ProviderPicker";
import { CreatingStep } from "./Steps/CreatingStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { DoneStep } from "./Steps/DoneStep";

// Generous timeout — first-time setup pulls + builds the agent image.
const START_TIMEOUT_MS = 5 * 60 * 1000;

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const [agentName, setAgentName] = useState("");
  const [personality, setPersonality] = useState<string | null>(null);
  // The full provider result from the picker — carries credentials/key plus the
  // chosen model and context window, all forwarded verbatim to setProvider.
  const [providerResult, setProviderResult] = useState<ProviderResult | null>(
    null,
  );
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    setStep("name");
    return () => setStep(null);
  }, []);

  useEffect(() => {
    if (step !== "creating" || !agentName || !personality || !providerResult)
      return;
    let cancelled = false;
    (async () => {
      try {
        // Phase 1: create the empty agent container.
        await createAgent(agentName);
        if (cancelled) return;

        // Phase 2: wait for the agent's HTTP server to be reachable.
        await waitUntilRunning(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        // Phase 3: set credentials + preferences (provider, personality, model, context, timezone).
        await setProvider(
          agentName,
          providerResult,
          personality ?? undefined,
          Intl.DateTimeFormat().resolvedOptions().timeZone,
        );
        if (cancelled) return;

        // Phase 4: wait for the provision-triggered restart to settle.
        await waitUntilAlive(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        setStep("done");
      } catch (e) {
        if (cancelled) return;
        setCreateError(errorMessage(e, "creation failed"));
        setProviderResult(null);
        setStep("name");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, agentName, personality, providerResult, setStep]);

  const content = (() => {
    if (step === "provider")
      return (
        <ProviderPicker
          defaultsOnly
          onDone={(result) => {
            // The picker handles OAuth/key + defaults internally and hands
            // back a complete result; forward it verbatim to setProvider.
            // Model/context stay editable later in AgentSettings.
            setProviderResult(result);
            setStep("personality");
          }}
          onBack={() => setStep("name")}
        />
      );
    if (step === "personality")
      return (
        <PersonalityStep
          onPicked={(name) => {
            setPersonality(name);
            setStep("creating");
          }}
        />
      );
    if (step === "creating") return <CreatingStep agentName={agentName} />;
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
          <motion.div key={step} {...stepTransition}>
            {content}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
