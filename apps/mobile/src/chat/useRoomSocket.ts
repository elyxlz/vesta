import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import * as Crypto from "expo-crypto";
import {
  createChatSession,
  roomHoldKey,
  roomsSocketPath,
  type ChatAttachment,
  type ChatSession,
  type Controller,
  type InputMethod,
} from "@vesta/core";
import { useChatSession, useSyncState } from "@vesta/core/react";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { setVisibleRoomSocket } from "@/notifications/foreground-policy";
import { agentHolds } from "@/holds/agent-holds";

// A slot whose occupant the effect owns, read through useSyncExternalStore: the session is
// created by the effect whose cleanup closes it, so the two lifetimes cannot diverge.
function createSessionSlot() {
  let current: ChatSession | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set: (next: ChatSession | null) => {
      current = next;
      for (const listener of listeners) listener();
    },
  };
}

// The mobile adapter over core's chat session, one per room: it injects the platform ports (the
// session's token-stamped socket URL, expo-crypto ids, the pacing preference) and the
// stale-while-reconnecting hold, which seeds the session across a controller epoch so backgrounding
// never blanks the chat and receives every commit so a popped screen keeps its tail. It also
// registers the room as the visible conversation, which is what defers a foreground notification
// for the chat already on screen.
export function useRoomSocket(
  roomId: string,
  // Whose pacing preference this conversation follows: a direct room reads its own agent's choice,
  // a room with several members paces naturally.
  pacingAgent: string | null,
  controller: Controller | null,
) {
  const preferences = usePreferences();
  const { connection } = useSession();
  const key = roomHoldKey(roomId, connectionKeyOf(connection) ?? "");
  const naturalPacing =
    pacingAgent === null || preferences.naturalChatPacingForAgent(pacingAgent);
  // Read by the session at each pacing step, so a preference flip lands without a rebuild.
  const naturalPacingRef = useRef(naturalPacing);
  useEffect(() => {
    naturalPacingRef.current = naturalPacing;
  }, [naturalPacing]);

  const connected = useSyncState(controller) === "open";
  const [slot] = useState(createSessionSlot);
  const session = useSyncExternalStore(slot.subscribe, slot.get);

  useEffect(() => {
    if (!roomId || !controller) return;
    const created = createChatSession({
      http: controller.http,
      roomId,
      buildUrl: () =>
        controller.session.websocketUrl(
          roomsSocketPath(),
          new URLSearchParams({ room: roomId }),
        ),
      makeId: () => Crypto.randomUUID(),
      naturalPacing: () => naturalPacingRef.current,
      initialState: agentHolds.chat.read(key) ?? undefined,
    });
    // The key is captured here, so a commit from a previous room/gateway epoch can only ever
    // write its own cell, never the next one's.
    const unsubscribe = created.subscribe(() => {
      agentHolds.chat.persist(key, created.getState().chat);
    });
    slot.set(created);
    return () => {
      unsubscribe();
      created.close();
      slot.set(null);
    };
  }, [roomId, controller, key, slot]);

  useEffect(
    () => setVisibleRoomSocket(connection?.url ?? "", roomId, connected),
    [connection?.url, roomId, connected],
  );

  // A preference flip mid-conversation commits whatever was still typing out.
  useEffect(() => {
    if (!naturalPacing) slot.get()?.flushPacing();
  }, [naturalPacing, slot]);

  const state = useChatSession(session);

  const send = useCallback(
    (
      text: string,
      inputMethod: InputMethod = "typed",
      attachments?: ChatAttachment[],
    ): boolean => {
      const live = slot.get();
      if (!live) return false;
      live.send(text, inputMethod, attachments);
      return true;
    },
    [slot],
  );
  const retry = useCallback(
    (
      intentId: string,
      text: string,
      inputMethod: InputMethod = "typed",
      attachments?: ChatAttachment[],
    ) => {
      slot.get()?.retry(intentId, text, inputMethod, attachments);
    },
    [slot],
  );
  const loadMore = useCallback(
    (): Promise<void> => slot.get()?.loadMore() ?? Promise.resolve(),
    [slot],
  );
  const trimHistory = useCallback(() => {
    slot.get()?.trimHistory();
  }, [slot]);
  const reportSpeaking = useCallback(
    (speaking: boolean) => {
      slot.get()?.reportSpeaking(speaking);
    },
    [slot],
  );

  // Memoized so the chat context built on top of it only changes identity when a consumed field
  // does; otherwise every provider render would re-render all four agent pages.
  return useMemo(
    () => ({
      events: state.chat.messages,
      isTyping: state.typing,
      connected,
      historyLoaded: state.chat.historyLoaded,
      latestLiveChat: state.latestReply,
      hasMore: state.chat.cursor !== null,
      loadingMore: state.loadingMore,
      loadMore,
      trimHistory,
      send,
      retry,
      reportSpeaking,
      reseedRevision: state.reseedRevision,
    }),
    [state, connected, loadMore, trimHistory, send, retry, reportSpeaking],
  );
}

export type RoomSocket = ReturnType<typeof useRoomSocket>;
