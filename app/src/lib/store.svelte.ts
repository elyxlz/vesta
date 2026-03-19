import type { PlatformStatus } from "./types";

// ── Per-box operation state ────────────────────────────────────

export type BoxOperation = "idle" | "stopping" | "starting" | "authenticating" | "deleting" | "rebuilding" | "backing-up" | "restoring";

type BoxOpState = {
  operation: BoxOperation;
  error: string;
};

let boxStates = $state<Record<string, BoxOpState>>({});

export function getBoxOp(name: string): BoxOpState {
  return boxStates[name] ?? { operation: "idle", error: "" };
}

export function setBoxOp(name: string, operation: BoxOperation, error = "") {
  boxStates[name] = { operation, error };
}

export function setBoxError(name: string, error: string) {
  const current = boxStates[name];
  if (current) {
    boxStates[name] = { ...current, error };
  } else {
    boxStates[name] = { operation: "idle", error };
  }
}

export function clearBoxOp(name: string) {
  boxStates[name] = { operation: "idle", error: "" };
}

export function removeBoxState(name: string) {
  const { [name]: _, ...rest } = boxStates;
  boxStates = rest;
}

export function busyBoxName(): string | null {
  for (const [name, state] of Object.entries(boxStates)) {
    if (state.operation !== "idle") return name;
  }
  return null;
}

// ── Onboarding state ───────────────────────────────────────────

export type OnboardingStep = "platform" | "name" | "creating" | "auth" | "done";

type OnboardingState = {
  step: OnboardingStep;
  name: string;
  error: { friendly: string | null; raw: string } | null;
  showRawError: boolean;
  platform: PlatformStatus | null;
  authUrl: string | null;
  authCodeNeeded: boolean;
  authCodeSubmitted: boolean;
  authCode: string;
  busy: boolean;
  createMsg: string;
};

const DEFAULT_ONBOARDING: OnboardingState = {
  step: "platform",
  name: "",
  error: null,
  showRawError: false,
  platform: null,
  authUrl: null,
  authCodeNeeded: false,
  authCodeSubmitted: false,
  authCode: "",
  busy: false,
  createMsg: "",
};

let onboarding = $state<OnboardingState>({ ...DEFAULT_ONBOARDING });

export function getOnboarding(): OnboardingState {
  return onboarding;
}

export function updateOnboarding(patch: Partial<OnboardingState>) {
  onboarding = { ...onboarding, ...patch };
}

export function resetOnboarding() {
  onboarding = { ...DEFAULT_ONBOARDING };
}
