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
  agentHoldKey,
  chatSocketPath,
  createChatSession,
  type ChatAttachment,
  type ChatSession,
  type Controller,
  type InputMethod,
  type Tree,
} from "@vesta/core";
import { useChatSession, useReplica, useSyncState } from "@vesta/core/react";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import {
  agentActivitySnapshotsEqual,
  selectAgentActivitySnapshot,
} from "./agent-activity-model";
import { agentHolds } from "@/holds/agent-holds";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

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

// The mobile adapter over core's chat session: it injects the platform ports (the session's
// token-stamped socket URL, expo-crypto ids, the pacing preference) and the stale-while-reconnecting
// hold, which seeds the session across a controller epoch so backgrounding never blanks the chat and
// receives every commit so a popped screen keeps its tail.
export function useAgentSocket(
  name: string,
  active: boolean,
  controller: Controller | null,
) {
  const preferences = usePreferences();
  const { connection } = useSession();
  const key = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  const naturalPacing = preferences.naturalChatPacingForAgent(name);
  // Read by the session at each pacing step, so a preference flip lands without a rebuild.
  const naturalPacingRef = useRef(naturalPacing);
  useEffect(() => {
    naturalPacingRef.current = naturalPacing;
  }, [naturalPacing]);

  const connected = useSyncState(controller) === "open";
  const [slot] = useState(createSessionSlot);
  const session = useSyncExternalStore(slot.subscribe, slot.get);

  useEffect(() => {
    if (!active || !name || !controller) return;
    const agent = name;
    const created = createChatSession({
      http: controller.http,
      agent,
      buildUrl: () => controller.session.websocketUrl(chatSocketPath(agent)),
      makeId: () => Crypto.randomUUID(),
      naturalPacing: () => naturalPacingRef.current,
      initialState: agentHolds.chat.read(key) ?? undefined,
    });
    // The key is captured here, so a commit from a previous agent/gateway epoch can only ever
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
  }, [active, name, controller, key, slot]);

  // A preference flip mid-conversation commits whatever was still typing out.
  useEffect(() => {
    if (!naturalPacing) slot.get()?.flushPacing();
  }, [naturalPacing, slot]);

  const state = useChatSession(session);

  const activitySelector = useCallback(
    (tree: Tree | null) => selectAgentActivitySnapshot(tree, active, name),
    [active, name],
  );
  const agentActivity = useReplica(
    controller?.replica ?? null,
    activitySelector,
    agentActivitySnapshotsEqual,
  );

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      name
        ? (tree?.agents[name]?.notifications.pending ?? []).flatMap((notif) =>
            notif.notif_id ? [notif.notif_id] : [],
          )
        : [],
    [name],
  );
  const pendingNotifications = useReplica(
    controller?.replica ?? null,
    pendingSelector,
    idsEqual,
  );

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

  // Memoized so the AgentContext value built on top of it only changes identity when a consumed
  // field does; otherwise every provider render would re-render all four agent pages.
  return useMemo(
    () => ({
      events: state.chat.messages,
      agentState: agentActivity.state,
      agentStateReady: agentActivity.ready,
      isTyping: state.typing,
      connected,
      historyLoaded: state.chat.historyLoaded,
      pendingNotifications,
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
    [
      state,
      agentActivity.state,
      agentActivity.ready,
      connected,
      pendingNotifications,
      loadMore,
      trimHistory,
      send,
      retry,
      reportSpeaking,
    ],
  );
}
