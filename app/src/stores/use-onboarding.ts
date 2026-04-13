import { create } from "zustand";

export type OnboardingStep =
  | "name"
  | "creating"
  | "auth"
  | "finalizing"
  | "done";

interface OnboardingState {
  step: OnboardingStep | null;
  setStep: (step: OnboardingStep | null) => void;
}

export const useOnboarding = create<OnboardingState>((set) => ({
  step: null,
  setStep: (step) => set({ step }),
}));
