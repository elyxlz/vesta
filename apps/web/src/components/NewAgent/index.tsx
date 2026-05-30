import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createAgent } from "@/api";
import {
  setProvider,
  waitUntilRunning,
  waitUntilAlive,
  type OpenRouterConfig,
  type ProviderResult,
} from "@/api/agents";
import { fadeSlide } from "@/lib/motion";
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
  const [seedPersonality, setSeedPersonality] = useState<string | null>(null);
  const [openrouter, setOpenrouter] = useState<OpenRouterConfig | null>(null);
  const [credentials, setCredentials] = useState<string | null>(null);
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
        // Phase 1: create the empty agent container.
        await createAgent(agentName, seedPersonality);
        if (cancelled) return;

        // Phase 2: wait for the agent's HTTP server to be reachable.
        await waitUntilRunning(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        // Phase 3: provision the provider via POST /agents/{name}/provider.
        const result: ProviderResult =
          openrouter !== null
            ? { kind: "openrouter", config: openrouter }
            : { kind: "claude", credentials: credentials ?? "" };
        await setProvider(agentName, result);
        if (cancelled) return;

        // Phase 4: wait for the provision-triggered restart to settle.
        await waitUntilAlive(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        setStep("done");
      } catch (e) {
        if (cancelled) return;
        setCreateError(
          (e as { message?: string })?.message || "creation failed",
        );
        setCredentials(null);
        setOpenrouter(null);
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
          onDone={(result) => {
            // Single result type now — ProviderPicker handles OAuth internally.
            if (result.kind === "openrouter") {
              setOpenrouter(result.config);
              setCredentials(null);
            } else {
              setCredentials(result.credentials);
              setOpenrouter(null);
            }
            setStep("personality");
          }}
          onBack={() => setStep("name")}
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
