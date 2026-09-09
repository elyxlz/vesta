import { useCallback } from "react";
import { createKeyedHoldStore, roomHoldKey } from "@vesta/core";
import { useHeld } from "@vesta/core/react";
import { getConnection } from "@/lib/connection";

// The composer draft is held above the chat route, per room and per gateway, so leaving for
// Home, switching conversation, or a second mounted Chat (the desktop panel and the fullscreen
// route) never loses or leaks half-typed text. Memory only, like mobile: a reload starts clean.
export const chatDrafts = createKeyedHoldStore<string>();

export function useChatDraft(roomId: string): [string, (text: string) => void] {
  const key = roomHoldKey(roomId, getConnection()?.url ?? "");
  const draft = useHeld(chatDrafts, key) ?? "";
  const setDraft = useCallback(
    (text: string) => {
      chatDrafts.persist(key, text);
    },
    [key],
  );
  return [draft, setDraft];
}
