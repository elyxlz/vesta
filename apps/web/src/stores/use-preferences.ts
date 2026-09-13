import { create } from "zustand";
import { persist } from "zustand/middleware";

// How the mic is triggered. Both dictate; "hold" confirms on release, "toggle" waits for
// the confirm button.
export type VoiceActivationMode = "toggle" | "hold";

// Every per-device preference, in one persisted store. Each field is remembered on this
// device alone and nothing sets it fleet-wide.
interface Preferences {
  // Natural chat pacing, per agent (default on).
  naturalPacingByAgent: Record<string, boolean>;
  // This device's location sharing switch: on makes the presence reporter ask the browser for
  // a fix, so the OS permission prompt is the real consent; off retracts the stored position.
  shareLocation: boolean;
  voiceActivation: VoiceActivationMode;
  voiceMuted: boolean;
  conversationAutoEnd: boolean;
  conversationYield: boolean;
  // Agents whose desktop panel remembers a collapsed chat with the dashboard full-page.
  chatCollapsed: string[];
  // The most recently opened agent, so the home carousel can center it on return.
  lastAgent: string | null;
  // The gateway version whose release notes this browser has seen.
  whatsNewLastSeen: string | null;
}

interface PreferencesState extends Preferences {
  update: (patch: Partial<Preferences>) => void;
}

const DEFAULTS: Preferences = {
  naturalPacingByAgent: {},
  shareLocation: true,
  voiceActivation: "toggle",
  voiceMuted: false,
  conversationAutoEnd: true,
  conversationYield: true,
  chatCollapsed: [],
  lastAgent: null,
  whatsNewLastSeen: null,
};

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      update: (patch) => set(patch),
    }),
    { name: "vesta-preferences", version: 1 },
  ),
);

export function naturalPacingFor(agent: string): boolean {
  return usePreferences.getState().naturalPacingByAgent[agent] ?? true;
}

export function setChatCollapsed(agent: string, collapsed: boolean): void {
  const { chatCollapsed, update } = usePreferences.getState();
  const without = chatCollapsed.filter((name) => name !== agent);
  update({ chatCollapsed: collapsed ? [...without, agent] : without });
}
