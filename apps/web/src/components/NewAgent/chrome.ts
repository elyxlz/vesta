import type { OnboardingStep } from "@/stores/use-onboarding";

export type ChromeActionKind =
  "submit-name" | "submit-vibe" | "open-chat" | "retry";

export interface ChromeHeading {
  title: string;
  description: string;
}

export interface ChromeAction {
  kind: ChromeActionKind;
  label: string;
  disabled: boolean;
}

export interface StepChrome {
  heading: ChromeHeading | null;
  action: ChromeAction | null;
  widthClass: string;
  // The action button keeps the compact width even under the wide vibe grid.
  actionWidthClass: string;
}

const NARROW = "w-[320px]";
const WIDE = "w-[672px]";

// One owner for what the persistent shell shows per step: the heading copy,
// the single morphing action, and the step's content width.
export function stepChrome({
  step,
  nameValid,
  vibeReady,
  failed,
}: {
  step: OnboardingStep;
  nameValid: boolean;
  vibeReady: boolean;
  failed: boolean;
}): StepChrome {
  if (step === "name") {
    return {
      heading: {
        title: "new agent",
        description: "give them a name to get started.",
      },
      action: { kind: "submit-name", label: "continue", disabled: !nameValid },
      widthClass: NARROW,
      actionWidthClass: NARROW,
    };
  }
  if (step === "provider") {
    return {
      heading: null,
      action: null,
      widthClass: "",
      actionWidthClass: "",
    };
  }
  if (step === "personality") {
    return {
      heading: {
        title: "pick a vibe",
        description:
          "starting point, not a commitment. ask your agent to change it anytime, and it'll keep shifting as they get to know you.",
      },
      action: { kind: "submit-vibe", label: "continue", disabled: !vibeReady },
      widthClass: WIDE,
      actionWidthClass: NARROW,
    };
  }
  if (step === "done") {
    return {
      heading: null,
      action: { kind: "open-chat", label: "say hi", disabled: false },
      widthClass: NARROW,
      actionWidthClass: NARROW,
    };
  }
  return {
    heading: null,
    action: failed
      ? { kind: "retry", label: "try again", disabled: false }
      : null,
    widthClass: NARROW,
    actionWidthClass: NARROW,
  };
}
