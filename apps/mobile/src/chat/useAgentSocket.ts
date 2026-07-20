import { useCallback, useEffect, useRef, useState } from "react";
import * as Crypto from "expo-crypto";
import {
  PACING,
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
  sendMessage,
  typingDelay,
  type ChatMessage,
  type ChatState,
  type Delta,
  type InputMethod,
  type SendFailure,
  type Tree,
  type VestaEvent,
} from "@vesta/core";
import { useReplica, useSyncState, useWatch } from "@vesta/core/react";
import { useController } from "@/controller/context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { useChatHold } from "./ChatHoldProvider";
import {
  captureChatHold,
  chatHoldKey,
  heldChatState,
} from "./chat-hold-model";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

interface HistoryPage {
  events: VestaEvent[];
  cursor: number | null;
}

// The chat view-model over the core controller. useWatch turns the agent's live edge on;
// controller.subscribeDeltas feeds the chat tail (append/resync are not tree state, so they arrive
// here, not through the replica). agentState + pending come from the replica; connectedness from the
// single sync socket. There is no per-agent WS: the tail is the HTTP history page plus live appends,
// deduped at the seam by event id, and sends are POST intents confirmed by their append echo. The
// socket lifecycle (connect, backoff, background teardown) is the controller's; this hook only reads.
export function useAgentSocket(name: string, active: boolean) {
  const controller = useController();
  const preferences = usePreferences();
  const { connection } = useSession();
  const holdStore = useChatHold();
  const key = chatHoldKey(name, connectionKeyOf(connection) ?? "");
  const keyRef = useRef(key);
  keyRef.current = key;
  const naturalPacing = preferences.naturalChatPacingForAgent(name);
  const naturalPacingRef = useRef(naturalPacing);
  naturalPacingRef.current = naturalPacing;

  useWatch(controller, active && name ? name : null);
  const connected = useSyncState(controller) === "open";

  const activitySelector = useCallback(
    (tree: Tree | null) =>
      active && name ? (tree?.agents[name]?.info.activityState ?? "idle") : "idle",
    [active, name],
  );
  const agentState = useReplica(controller.replica, activitySelector);

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      name
        ? (tree?.agents[name]?.notifications.pending ?? []).flatMap((notif) =>
            notif.notif_id ? [notif.notif_id] : [],
          )
        : [],
    [name],
  );
  const pendingNotifications = useReplica(controller.replica, pendingSelector, idsEqual);

  // ChatState is the model's single source of truth. It lives in a ref (synchronous, so a batch of
  // appends dedups against the running accumulation) mirrored into React state for rendering. It is
  // seeded from the hold so a conversation renders immediately (stale) across a controller epoch
  // instead of blanking to a skeleton; seedTail refetches and merges by id. Every commit persists the
  // render slice back to the hold under the current key, so a background/foreground survives it.
  const [state, setState] = useState<ChatState>(
    () => heldChatState(holdStore.read(), key) ?? initialChatState(),
  );
  const stateRef = useRef<ChatState>(state);
  const commit = useCallback(
    (fold: (current: ChatState) => ChatState) => {
      stateRef.current = fold(stateRef.current);
      setState(stateRef.current);
      holdStore.persist(captureChatHold(keyRef.current, stateRef.current));
    },
    [holdStore],
  );

  const [isTyping, setIsTyping] = useState(false);
  const [latestLiveChat, setLatestLiveChat] = useState<string | null>(null);
  const [reseedRevision, setReseedRevision] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);

  const chatQueueRef = useRef<ChatMessage[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTypingTimer = useCallback(() => {
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = null;
  }, []);

  const resetTyping = useCallback(() => {
    clearTypingTimer();
    chatQueueRef.current = [];
    drainingRef.current = false;
    setIsTyping(false);
  }, [clearTypingTimer]);

  const flushQueue = useCallback(() => {
    clearTypingTimer();
    const queued = chatQueueRef.current;
    chatQueueRef.current = [];
    drainingRef.current = false;
    for (const event of queued) {
      commit((current) => commitPacedChat(current, event));
      if (event.type === "chat") setLatestLiveChat(event.text);
    }
    setIsTyping(false);
  }, [clearTypingTimer, commit]);

  const drainQueue = useCallback(function drainQueue() {
    if (drainingRef.current) return;
    const queue = chatQueueRef.current;
    const next = queue[0];
    if (next === undefined) {
      setIsTyping(false);
      return;
    }
    if (queue.length > PACING.flushThreshold || !naturalPacingRef.current) {
      flushQueue();
      return;
    }
    drainingRef.current = true;
    setIsTyping(true);
    const delay = typingDelay(next.type === "chat" ? next.text.length : 0);
    typingTimerRef.current = setTimeout(() => {
      typingTimerRef.current = null;
      queue.shift();
      commit((current) => commitPacedChat(current, next));
      if (next.type === "chat") setLatestLiveChat(next.text);
      drainingRef.current = false;
      drainQueue();
    }, delay);
  }, [commit, flushQueue]);

  const enqueueChat = useCallback(
    (event: ChatMessage) => {
      chatQueueRef.current.push(event);
      drainQueue();
    },
    [drainQueue],
  );

  useEffect(() => {
    if (!naturalPacing) flushQueue();
  }, [flushQueue, naturalPacing]);

  const fetchPage = useCallback(
    (cursor?: number): Promise<HistoryPage> => {
      const parameters = new URLSearchParams();
      if (cursor !== undefined) parameters.set("cursor", String(cursor));
      const qs = parameters.toString();
      return controller.http.json<HistoryPage>(
        `/agents/${encodeURIComponent(name)}/app-chat/history${qs ? `?${qs}` : ""}`,
      );
    },
    [controller, name],
  );

  useEffect(() => {
    if (!active || !name) return;
    const agent = name;
    let cancelled = false;

    // Seed from the hold for this key (survives the controller epoch); a mismatched key clears to
    // empty at the read, so a switched agent or gateway never renders the prior conversation.
    const seeded = heldChatState(holdStore.read(), key) ?? initialChatState();
    stateRef.current = seeded;
    setState(seeded);
    resetTyping();

    // Reseed the tail from the newest history page and MERGE, never replace. Serves the initial load
    // and a resync alike, bumping reseedRevision so the notifications page refetches its own history.
    const seed = async () => {
      const page = await fetchPage();
      if (cancelled) return;
      commit((current) => seedTail(current, page));
      setReseedRevision((revision) => revision + 1);
    };

    const addLiveEvent = (event: ChatMessage) => {
      const { state: next, paced } = foldLiveEvent(stateRef.current, event);
      commit(() => next);
      if (paced) enqueueChat(event);
      else if (event.type === "error" || event.type === "rate_limited") resetTyping();
    };

    void seed().catch((error: unknown) => {
      console.warn("chat: history load failed", error);
    });

    const unsubscribe = controller.subscribeDeltas((delta: Delta) => {
      if (delta.type === "append" && delta.agent === agent) {
        for (const event of delta.events) addLiveEvent(event);
      } else if (delta.type === "resync" && delta.agent === agent) {
        resetTyping();
        void seed().catch((error: unknown) => {
          console.warn("chat: resync refetch failed", error);
        });
      }
    });

    return () => {
      cancelled = true;
      unsubscribe();
      resetTyping();
    };
  }, [
    active,
    name,
    controller,
    key,
    holdStore,
    commit,
    resetTyping,
    enqueueChat,
    fetchPage,
  ]);

  // Reflect the POST's settled disposition into the bubble. A null outcome means queued-on-tap:
  // delivery truth is the append echo (which clears send_state), so only a failure marks the bubble.
  const applyOutcome = useCallback(
    (intentId: string, outcome: Promise<SendFailure | null>) => {
      void outcome.then((failure) => {
        if (failure) commit((current) => markSend(current, intentId, failure));
      });
    },
    [commit],
  );

  const send = useCallback(
    (text: string, inputMethod: InputMethod = "typed"): boolean => {
      if (!name) return false;
      const { id, outcome } = sendMessage(
        controller.http,
        name,
        { text, input_method: inputMethod },
        () => Crypto.randomUUID(),
      );
      commit((current) => beginSend(current, text, inputMethod, id));
      applyOutcome(id, outcome);
      return true;
    },
    [name, controller, commit, applyOutcome],
  );

  // Re-post a failed/retryable bubble under its ORIGINAL intent id (idempotent): the bubble returns
  // to "sending" and confirms on the same echo. Text + input method come from the bubble tapped.
  const retry = useCallback(
    (intentId: string, text: string, inputMethod: InputMethod = "typed") => {
      if (!name) return;
      commit((current) => markSend(current, intentId, "sending"));
      const { outcome } = sendMessage(
        controller.http,
        name,
        { text, input_method: inputMethod },
        () => intentId,
      );
      applyOutcome(intentId, outcome);
    },
    [name, controller, commit, applyOutcome],
  );

  const hasMore = state.cursor !== null;

  const loadMore = useCallback(async (): Promise<void> => {
    if (!name || loadingMoreRef.current || stateRef.current.cursor === null) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await fetchPage(stateRef.current.cursor);
      commit((current) => prependPage(current, page.events, page.cursor));
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [name, fetchPage, commit]);

  return {
    events: state.messages,
    agentState,
    isTyping,
    connected,
    historyLoaded: state.historyLoaded,
    pendingNotifications,
    latestLiveChat,
    hasMore,
    loadingMore,
    loadMore,
    send,
    retry,
    reseedRevision,
  };
}
