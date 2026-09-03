import { create } from "zustand";
import { persist } from "zustand/middleware";

// How the mic is triggered. Both dictate; "hold" confirms on release, "toggle" waits for
// the confirm button.
export type VoiceActivationMode = "toggle" | "hold";

// Every per-device preference, in one persisted store. Each field is remembered on this
// device alone and nothing sets it fleet-wide.
export interface Preferences {
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

// LEGACY(remove-when: MIN_SUPPORTED_CLIENT_VERSION is above 0.2.17): the values a device stored
// under the per-feature keys, read once as the seed the first persisted blob replaces.
function legacyPreferences(): Preferences {
  if (typeof localStorage === "undefined") return DEFAULTS;
  const flag = (key: string, fallback: boolean) => {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  };
  let naturalPacingByAgent: Record<string, boolean> = {};
  const rawPacing = localStorage.getItem("chat-natural-pacing-by-agent");
  if (rawPacing) {
    try {
      const parsed: unknown = JSON.parse(rawPacing);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        naturalPacingByAgent = Object.fromEntries(
          Object.entries(parsed).filter(
            (entry): entry is [string, boolean] =>
              typeof entry[1] === "boolean",
          ),
        );
      }
    } catch {
      naturalPacingByAgent = {};
    }
  }
  const collapsedPrefix = "vesta:chat-collapsed:";
  const chatCollapsed = Object.keys(localStorage)
    .filter((key) => key.startsWith(collapsedPrefix))
    .map((key) => key.slice(collapsedPrefix.length));
  return {
    naturalPacingByAgent,
    shareLocation: localStorage.getItem("vesta:share-location") !== "off",
    voiceActivation:
      localStorage.getItem("voice-activation") === "hold" ? "hold" : "toggle",
    voiceMuted: flag("voice-muted", false),
    conversationAutoEnd: flag("voice-conversation-auto-end", true),
    conversationYield: flag("voice-conversation-yield", true),
    chatCollapsed,
    lastAgent: localStorage.getItem("vesta:last-agent"),
    whatsNewLastSeen: localStorage.getItem("vesta:whats-new-last-seen"),
  };
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      ...legacyPreferences(),
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
