// The non-sensitive inputs collected while creating a new agent, persisted so a page refresh
// mid-onboarding resumes instead of restarting from the name. The provider result (OAuth blob /
// API key) is deliberately never stored: a resumed run re-collects the provider, then skips every
// step it already has. Scoped to sessionStorage so it lives for the tab's onboarding, not forever.
const STORAGE_KEY = "vesta:onboarding";

export interface OnboardingProgress {
  agentName: string;
  personality: string | null;
}

export function loadOnboarding(): OnboardingProgress | null {
  if (typeof sessionStorage === "undefined") return null;
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  let parsed: { agentName?: unknown; personality?: unknown };
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed.agentName !== "string" || !parsed.agentName) return null;
  return {
    agentName: parsed.agentName,
    personality:
      typeof parsed.personality === "string" ? parsed.personality : null,
  };
}

export function saveOnboarding(progress: OnboardingProgress): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
}

export function clearOnboarding(): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.removeItem(STORAGE_KEY);
}
