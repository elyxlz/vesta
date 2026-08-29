import { create } from "zustand";

// Natural pacing is a per-agent, per-device feel (default on): the switch lives on each agent's
// settings page and nothing sets it fleet-wide.
const STORAGE_KEY = "chat-natural-pacing-by-agent";

interface ChatPacingState {
  byAgent: Record<string, boolean>;
  naturalFor: (agent: string) => boolean;
  setNatural: (agent: string, natural: boolean) => void;
}

function readStored(): Record<string, boolean> {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

export const useChatPacing = create<ChatPacingState>((set, get) => ({
  byAgent: readStored(),
  naturalFor: (agent) => get().byAgent[agent] ?? true,
  setNatural: (agent, natural) => {
    const byAgent = { ...get().byAgent, [agent]: natural };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(byAgent));
    set({ byAgent });
  },
}));
