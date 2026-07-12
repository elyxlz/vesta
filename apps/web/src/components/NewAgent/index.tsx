import { useEffect, useRef, useState } from "react";
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
import { useLayout } from "@/stores/use-layout";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { ProviderPicker } from "@/components/ProviderPicker";
import { CreatingStep } from "./Steps/CreatingStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { classifyCreateFailure, isCredentialRejection } from "./create-flow";

// Generous timeout — first-time setup pulls + builds the agent image.
const START_TIMEOUT_MS = 10 * 60 * 1000;

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const [agentName, setAgentName] = useState("");
  const [personality, setPersonality] = useState<string | null>(null);
  // The full provider result from the picker — credentials/key plus the default
  // model and context window, all forwarded verbatim to setProvider.
  const [providerResult, setProviderResult] = useState<ProviderResult | null>(
    null,
  );
  const [createError, setCreateError] = useState<string | null>(null);
  // Pipeline runs for the current name; a retry treats createAgent's 409 as
  // phase 1 already done (the failed attempt made the container).
  const attemptRef = useRef(0);

  useEffect(() => {
    setStep("name");
    return () => setStep(null);
  }, []);

  useEffect(() => {
    if (step !== "creating" || createError !== null) return;
    if (!agentName || !personality || !providerResult) return;
    let cancelled = false;
    attemptRef.current += 1;
    const firstAttempt = attemptRef.current === 1;
    (async () => {
      try {
        // Phase 1: create the empty agent container.
        try {
          await createAgent(agentName);
        } catch (e) {
          const failure = classifyCreateFailure(e, firstAttempt);
          if (failure === "name-rejected") {
            // A rejected name never counts as an attempt: resubmitting it
            // unchanged must not read the next 409 as "already created".
            attemptRef.current = 0;
            if (!cancelled) {
              setCreateError(errorMessage(e, "creation failed"));
              setStep("name");
            }
            return;
          }
          if (failure === "retryable") throw e;
        }
        if (cancelled) return;

        // Phase 2: wait for the agent's HTTP server to be reachable.
        await waitUntilRunning(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        // Phase 3: set credentials + preferences (provider, personality, model, context, timezone).
        try {
          await setProvider(
            agentName,
            providerResult,
            personality,
            Intl.DateTimeFormat().resolvedOptions().timeZone,
          );
        } catch (e) {
          if (isCredentialRejection(e)) {
            if (!cancelled) {
              setProviderResult(null);
              setCreateError(errorMessage(e, "provider setup failed"));
              setStep("provider");
            }
            return;
          }
          throw e;
        }
        if (cancelled) return;

        // Phase 4: wait for the provision-triggered restart to settle.
        await waitUntilAlive(agentName, START_TIMEOUT_MS);
        if (cancelled) return;

        setStep("done");
      } catch (e) {
        // Transient failure: stay here with everything collected intact; the
        // retry button clears the error, which re-enters this pipeline.
        if (!cancelled) setCreateError(errorMessage(e, "creation failed"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [step, createError, agentName, personality, providerResult, setStep]);

  // Every input survives a failure, so re-entry skips whatever is already
  // collected: a fixed name jumps straight back to creating, a redone
  // credential skips the vibe it already has.
  const nextStep = (result: ProviderResult | null, vibe: string | null) => {
    if (!result) return "provider";
    if (!vibe) return "personality";
    return "creating";
  };

  const content = (() => {
    if (step === "provider")
      return (
        <div className="flex flex-col items-center gap-3">
          <ProviderPicker
            defaultsOnly
            onDone={(result) => {
              // The picker handles OAuth/key + defaults internally and hands
              // back a complete result; forward it verbatim to setProvider.
              // Model/context stay editable later in AgentSettings.
              setProviderResult(result);
              setCreateError(null);
              setStep(nextStep(result, personality));
            }}
            onBack={() => setStep("name")}
          />
          {createError && (
            <p className="text-xs text-destructive text-center px-4">
              {createError}
            </p>
          )}
        </div>
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
    if (step === "creating" || step === "done")
      return (
        <CreatingStep
          agentName={agentName}
          done={step === "done"}
          error={createError}
          onRetry={() => setCreateError(null)}
        />
      );
    return (
      <NameStep
        initialName={agentName}
        initialError={createError}
        onNamed={(name) => {
          if (name !== agentName) attemptRef.current = 0;
          setAgentName(name);
          setCreateError(null);
          setStep(nextStep(providerResult, personality));
        }}
      />
    );
  })();

  // "creating" and "done" share one mounted screen so the orb is continuous:
  // the same Orb lerps busy -> alive instead of remounting cold.
  const contentKey = step === "done" ? "creating" : step;

  // The step scrolls when it can't fit (a short screen + the tall personality
  // grid) instead of clipping. m-auto centers the child when it fits and pins it
  // to the top when it overflows, which justify-center can't (it clips the top in
  // a scroll container). Top padding clears the absolute navbar; bottom padding
  // clears the mobile home indicator.
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto overscroll-contain">
        <div
          className="flex min-h-full w-full flex-col"
          style={{
            paddingTop: `calc(${navbarHeight}px + 1rem)`,
            paddingBottom: "calc(env(safe-area-inset-bottom) + 1.5rem)",
          }}
        >
          <div className="m-auto flex w-full justify-center">
            <AnimatePresence mode="wait">
              <motion.div key={contentKey} {...stepTransition}>
                {content}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
