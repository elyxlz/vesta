import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { type ProviderResult } from "@/api/agents";
import { Button } from "@/components/ui/button";
import { usePersonalityCatalog } from "@/hooks/use-agent-catalogs";
import { errorMessage } from "@/lib/utils";
import { useLayout } from "@/stores/use-layout";
import { useToast } from "@/stores/use-toast";
import {
  clearOnboarding,
  loadOnboarding,
  saveOnboarding,
} from "@/lib/onboarding-progress";
import { useOnboarding, type OnboardingStep } from "@/stores/use-onboarding";
import { ProviderPicker } from "@/components/ProviderPicker";
import { NameStep } from "./Steps/NameStep";
import { CreatingStep } from "./Steps/CreatingStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { applyProviderSetup, prepareAgentShell } from "./create-flow";
import { Chrome } from "./Chrome";
import { stepChrome, type ChromeActionKind } from "./step-chrome";

const START_TIMEOUT_MS = 10 * 60 * 1000;
const PERSONALITY_STEPS = new Set<OnboardingStep>([
  "provider",
  "personality",
  "applying",
  "done",
]);
const LIFECYCLE_STEPS = new Set<OnboardingStep>([
  "creating",
  "applying",
  "done",
]);

function stepMatches(
  step: OnboardingStep | null,
  candidates: ReadonlySet<OnboardingStep>,
): boolean {
  return step !== null && candidates.has(step);
}

function selectedPersonality(
  draft: string | null,
  saved: string | null,
  fallback: string | undefined,
): string {
  return draft ?? saved ?? fallback ?? "";
}

export function NewAgent() {
  const step = useOnboarding((state) => state.step);
  const setStep = useOnboarding((state) => state.setStep);
  const navbarHeight = useLayout((state) => state.navbarHeight);
  const navigate = useNavigate();
  const toast = useToast();
  const [restored] = useState(loadOnboarding);
  const initialAgentName = restored?.agentName ?? "";
  const [agentName, setAgentName] = useState(initialAgentName);
  const [personality, setPersonality] = useState<string | null>(
    restored?.personality ?? null,
  );
  const [providerResult, setProviderResult] = useState<ProviderResult | null>(
    null,
  );
  const [createError, setCreateError] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState(initialAgentName);
  const [vibeDraft, setVibeDraft] = useState<string | null>(null);
  const attemptRef = useRef(initialAgentName ? 1 : 0);
  const personalityEnabled = stepMatches(step, PERSONALITY_STEPS);
  const {
    data: personalityCatalog,
    error: personalityError,
    retry: retryPersonalities,
  } = usePersonalityCatalog(agentName, personalityEnabled);
  const selectedVibe = selectedPersonality(
    vibeDraft,
    personality,
    personalityCatalog?.default,
  );

  const reportError = useCallback(
    (message: string) => {
      setCreateError(message);
      toast.error(message);
    },
    [toast],
  );
  const finishOnboarding = useCallback(() => {
    clearOnboarding();
    setStep("done");
  }, [setStep]);

  useEffect(() => {
    setStep(initialAgentName ? "creating" : "name");
    return () => setStep(null);
  }, [initialAgentName, setStep]);

  useEffect(() => {
    if (agentName) saveOnboarding({ agentName, personality });
  }, [agentName, personality]);

  useEffect(() => {
    if (step !== "creating" || createError !== null || !agentName) return;
    let cancelled = false;
    attemptRef.current += 1;
    const firstAttempt = attemptRef.current === 1;
    void prepareAgentShell(agentName, firstAttempt, START_TIMEOUT_MS)
      .then((result) => {
        if (cancelled) return;
        if (result.kind === "name-rejected") {
          attemptRef.current = 0;
          reportError(errorMessage(result.error, "creation failed"));
          setStep("name");
        } else if (result.kind === "ready") {
          finishOnboarding();
        } else {
          setStep("provider");
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setCreateError(errorMessage(caught, "creation failed"));
      });
    return () => {
      cancelled = true;
    };
  }, [step, createError, agentName, reportError, finishOnboarding, setStep]);

  useEffect(() => {
    if (step !== "applying" || createError !== null) return;
    if (!agentName || !personality || !providerResult) return;
    let cancelled = false;
    void applyProviderSetup({
      name: agentName,
      provider: providerResult,
      personality,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      timeoutMs: START_TIMEOUT_MS,
    })
      .then((result) => {
        if (cancelled) return;
        if (result.kind === "credential-rejected") {
          setProviderResult(null);
          reportError(errorMessage(result.error, "provider setup failed"));
          setStep("provider");
        } else if (result.kind === "needs-provider") {
          setProviderResult(null);
          reportError("the provider did not become ready");
          setStep("provider");
        } else {
          finishOnboarding();
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setCreateError(errorMessage(caught, "setup failed"));
      });
    return () => {
      cancelled = true;
    };
  }, [
    step,
    createError,
    agentName,
    personality,
    providerResult,
    reportError,
    finishOnboarding,
    setStep,
  ]);

  const name = nameDraft.trim();
  const submitName = () => {
    if (!name) return;
    if (name !== agentName) {
      attemptRef.current = 0;
      setProviderResult(null);
      setPersonality(null);
      setVibeDraft(null);
    }
    setAgentName(name);
    setCreateError(null);
    setStep("creating");
  };

  const handleAction = (kind: ChromeActionKind) => {
    if (kind === "submit-name") {
      submitName();
    } else if (kind === "submit-vibe") {
      setPersonality(selectedVibe);
      setStep("applying");
    } else if (kind === "open-chat") {
      void navigate(`/agent/${agentName}/chat`);
    } else {
      setCreateError(null);
    }
  };

  const content = (() => {
    if (step === "provider") {
      return (
        <ProviderPicker
          agentName={agentName}
          defaultsOnly
          choiceVariant="grid"
          onDone={(result) => {
            setProviderResult(result);
            setCreateError(null);
            setStep(personality ? "applying" : "personality");
          }}
          onBack={() => setStep("name")}
        />
      );
    }
    if (step === "personality") {
      if (personalityError) {
        return (
          <div className="flex flex-col items-center gap-3 px-4 text-center">
            <p className="text-xs text-destructive">{personalityError}</p>
            <Button
              type="button"
              variant="outline"
              onClick={retryPersonalities}
            >
              retry
            </Button>
          </div>
        );
      }
      return (
        <PersonalityStep
          personalities={personalityCatalog?.presets ?? null}
          selected={selectedVibe}
          onPick={setVibeDraft}
        />
      );
    }
    if (step === "creating" || step === "applying" || step === "done") {
      return (
        <CreatingStep
          agentName={agentName}
          stage={step === "applying" ? "applying" : "creating"}
          done={step === "done"}
          failed={createError !== null}
          error={createError}
        />
      );
    }
    return (
      <NameStep
        value={nameDraft}
        onChange={setNameDraft}
        onSubmit={submitName}
      />
    );
  })();

  const lifecycleStep = stepMatches(step, LIFECYCLE_STEPS);
  const contentKey = lifecycleStep ? "lifecycle" : step;
  const chrome = stepChrome({
    step: step ?? "name",
    nameValid: name !== "",
    vibeReady: personalityCatalog !== undefined && selectedVibe !== "",
    failed: createError !== null,
  });

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex-1 overflow-y-auto overscroll-contain mask-t-from-[calc(100%-var(--navbar-h)-72px)] mask-t-to-[calc(100%-var(--navbar-h))]"
        style={
          { "--navbar-h": `${String(navbarHeight)}px` } as React.CSSProperties
        }
      >
        <div
          className="flex min-h-full w-full flex-col"
          style={{
            paddingTop: `calc(${String(navbarHeight)}px + 1rem)`,
            paddingBottom: "calc(env(safe-area-inset-bottom) + 1.5rem)",
          }}
        >
          <div className="m-auto flex w-full justify-center">
            <Chrome
              heading={chrome.heading}
              action={chrome.action}
              bodyKey={contentKey ?? "name"}
              widthClass={chrome.widthClass}
              actionWidthClass={chrome.actionWidthClass}
              onAction={handleAction}
            >
              {content}
            </Chrome>
          </div>
        </div>
      </div>
    </div>
  );
}
