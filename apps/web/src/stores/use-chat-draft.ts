import { useCallback } from "react";
import { agentHoldKey, createKeyedHoldStore } from "@vesta/core";
import { useHeld } from "@vesta/core/react";
import { getConnection } from "@/lib/connection";

// The composer draft is held above the agent route, per agent and per gateway, so leaving for
// Home, switching agent, or a second mounted Chat (the desktop panel and the fullscreen route)
// never loses or leaks half-typed text. Memory only, like mobile: a reload starts clean.
export const chatDrafts = createKeyedHoldStore<string>();

export function useChatDraft(agent: string): [string, (text: string) => void] {
  const key = agentHoldKey(agent, getConnection()?.url ?? "");
  const draft = useHeld(chatDrafts, key) ?? "";
  const setDraft = useCallback(
    (text: string) => {
      chatDrafts.persist(key, text);
    },
    [key],
  );
  return [draft, setDraft];
}
