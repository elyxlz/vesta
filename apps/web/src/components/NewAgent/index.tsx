import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { createAgent } from "@/api";
import {
  setProvider,
  waitUntilRunning,
  waitUntilAlive,
  type ProviderResult,
} from "@/api/agents";
import { errorMessage } from "@/lib/utils";
import { useLayout } from "@/stores/use-layout";
import { useManifest } from "@/hooks/use-manifest";
import {
  loadOnboarding,
  saveOnboarding,
  clearOnboarding,
} from "@/lib/onboarding-progress";
import { useOnboarding } from "@/stores/use-onboarding";
import { NameStep } from "./Steps/NameStep";
import { ProviderPicker } from "@/components/ProviderPicker";
import { CreatingStep } from "./Steps/CreatingStep";
import { PersonalityStep } from "./Steps/PersonalityStep";
import { classifyCreateFailure, isCredentialRejection } from "./create-flow";
import { Chrome } from "./Chrome";
import { stepChrome, type ChromeActionKind } from "./chrome";

// Generous timeout — first-time setup pulls + builds the agent image.
const START_TIMEOUT_MS = 10 * 60 * 1000;

export function NewAgent() {
  const step = useOnboarding((s) => s.step);
  const setStep = useOnboarding((s) => s.setStep);
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const navigate = useNavigate();
  const manifest = useManifest();
  // Refreshing mid-onboarding restores the name and personality (never the credentials, which
  // stay in memory only); a resumed run re-collects the provider and skips whatever it already has.
  const [agentName, setAgentName] = useState(
    () => loadOnboarding()?.agentName ?? "",
  );
  const [personality, setPersonality] = useState<string | null>(
    () => loadOnboarding()?.personality ?? null,
  );
  // The full provider result from the picker — credentials/key plus the default
  // model and context window, all forwarded verbatim to setProvider.
  const [providerResult, setProviderResult] = useState<ProviderResult | null>(
    null,
  );
  const [createError, setCreateError] = useState<string | null>(null);
  // One reporter for every step error: the state drives the failed UI (dimmed
  // orb, retry, step routing) and the message itself surfaces as a toast.
  const reportError = (message: string) => {
    setCreateError(message);
    toast.error(message);
  };
  // Drafts the shell's single button commits: the name field's raw text and
  // the tile selection. personality stays committed only on continue, so the
  // resume-skip logic in nextStep keeps its meaning.
  const [nameDraft, setNameDraft] = useState(
    () => loadOnboarding()?.agentName ?? "",
  );
  const [vibeDraft, setVibeDraft] = useState<string | null>(null);
  const selectedVibe =
    vibeDraft ?? personality ?? manifest?.default_personality ?? "";
  // Pipeline runs for the current name; a retry treats createAgent's 409 as phase 1 already done
  // (the failed attempt made the container). A resumed refresh is such a retry, since the container
  // may already exist, so seed the count when the name was restored.
  const attemptRef = useRef(agentName ? 1 : 0);

  useEffect(() => {
    // No credentials survive a refresh, so a restored name resumes at the provider step; the
    // pipeline then skips any personality already collected. A fresh visit starts at the name.
    setStep(agentName ? "provider" : "name");
    return () => setStep(null);
  }, []);

  useEffect(() => {
    if (agentName) saveOnboarding({ agentName, personality });
  }, [agentName, personality]);

  useEffect(() => {
    if (step !== "creating" || createError !== null) return;
    if (!agentName || !personality || !providerResult) return;
    // Read through a call so each check re-reads the live flag: the cleanup flips it
    // between awaits, which a narrowed local can't see.
    let cancelled = false;
    const isCancelled = () => cancelled;
    attemptRef.current += 1;
    const firstAttempt = attemptRef.current === 1;
    const run = async () => {
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
            if (!isCancelled()) {
              reportError(errorMessage(e, "creation failed"));
              setStep("name");
            }
            return;
          }
          if (failure === "retryable") throw e;
        }
        if (isCancelled()) return;

        // Phase 2: wait for the agent's HTTP server to be reachable.
        await waitUntilRunning(agentName, START_TIMEOUT_MS);
        if (isCancelled()) return;

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
            if (!isCancelled()) {
              setProviderResult(null);
              reportError(errorMessage(e, "provider setup failed"));
              setStep("provider");
            }
            return;
          }
          throw e;
        }
        if (isCancelled()) return;

        // Phase 4: wait for the provision-triggered restart to settle.
        await waitUntilAlive(agentName, START_TIMEOUT_MS);
        if (isCancelled()) return;

        clearOnboarding();
        setStep("done");
      } catch (e) {
        // Transient failure: stay here with everything collected intact; the
        // retry button clears the error, which re-enters this pipeline.
        if (!isCancelled()) reportError(errorMessage(e, "creation failed"));
      }
    };
    void run();
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

  // The name is used verbatim (no normalization); the field already forbids
  // whitespace, so a non-empty draft is the whole rule. The gateway is the one
  // that validates it, and a rejection returns to this step with the error.
  const name = nameDraft.trim();
  const submitName = () => {
    if (!name) return;
    if (name !== agentName) attemptRef.current = 0;
    setAgentName(name);
    setCreateError(null);
    setStep(nextStep(providerResult, personality));
  };

  const handleAction = (kind: ChromeActionKind) => {
    if (kind === "submit-name") {
      submitName();
    } else if (kind === "submit-vibe") {
      setPersonality(selectedVibe);
      setStep("creating");
    } else if (kind === "open-chat") {
      void navigate(`/agent/${agentName}/chat`);
    } else {
      setCreateError(null);
    }
  };

  const content = (() => {
    if (step === "provider")
      return (
        <ProviderPicker
          defaultsOnly
          choiceVariant="grid"
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
      );
    if (step === "personality")
      return (
        <PersonalityStep
          personalities={manifest?.personalities ?? null}
          selected={selectedVibe}
          onPick={setVibeDraft}
        />
      );
    if (step === "creating" || step === "done")
      return (
        <CreatingStep
          agentName={agentName}
          done={step === "done"}
          failed={createError !== null}
        />
      );
    return (
      <NameStep
        value={nameDraft}
        onChange={setNameDraft}
        onSubmit={submitName}
      />
    );
  })();

  // "creating" and "done" share one mounted screen so the orb is continuous:
  // the same Orb lerps busy -> alive instead of remounting cold.
  const contentKey = step === "done" ? "creating" : step;

  const chrome = stepChrome({
    step: step ?? "name",
    nameValid: name !== "",
    vibeReady: manifest !== undefined && selectedVibe !== "",
    failed: createError !== null,
  });

  // The step scrolls when it can't fit (a short screen + the tall personality
  // grid) instead of clipping. m-auto centers the child when it fits and pins it
  // to the top when it overflows, which justify-center can't (it clips the top in
  // a scroll container). Top padding clears the absolute navbar; bottom padding
  // clears the mobile home indicator. The top mask dissolves scrolled content
  // over a long run before it slides under the transparent navbar; mask-t
  // positions run bottom-to-top, hence the 100% arithmetic.
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
