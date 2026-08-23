import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Crypto from "expo-crypto";
import {
  PACING,
  beginSend,
  commitPacedChat,
  createChatSocket,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
  sendMessage,
  serviceKeySocketUrl,
  typingDelay,
  type ChatMessage,
  type ChatState,
  type Controller,
  type InputMethod,
  type SendFailure,
  type Tree,
  type VestaEvent,
} from "@vesta/core";
import { createRnSocket } from "@/controller/rn-socket";
import {
  useOptionalControllerReplica,
  useOptionalControllerSyncState,
} from "@/controller/optional-controller-store";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import {
  agentActivitySnapshotsEqual,
  selectAgentActivitySnapshot,
} from "./agent-activity-model";
import { useAgentHolds } from "@/holds/AgentHoldsProvider";
import { agentHoldKey } from "@/holds/keyed-hold";

interface HistoryPage {
  events: VestaEvent[];
  cursor: number | null;
}

const SEED_RETRY_MS = 1_000;
const SEED_RETRY_MAX_MS = 30_000;

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

// The chat view-model over the core controller. The chat tail is a per-agent app-chat socket
// (replay-free: only events appended after connect) joined to the HTTP history page, deduped at the
// seam by event id; on every socket open the hook refetches the tail so a reconnect gap self-heals.
// agentState + pending come from the replica; gateway connectedness from the single sync socket.
// Sends are POST intents confirmed by their chat-socket echo. The stale-while-reconnecting hold gives
// an instant render across a controller epoch; backgrounding never blanks the chat.
export function useAgentSocket(
  name: string,
  active: boolean,
  controller: Controller | null,
) {
  const preferences = usePreferences();
  const { connection, api } = useSession();
  const apiRef = useRef(api);
  useEffect(() => {
    apiRef.current = api;
  }, [api]);
  const holds = useAgentHolds();
  const key = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  const naturalPacing = preferences.naturalChatPacingForAgent(name);
  const naturalPacingRef = useRef(naturalPacing);
  useEffect(() => {
    naturalPacingRef.current = naturalPacing;
  }, [naturalPacing]);

  const connected = useOptionalControllerSyncState(controller) === "open";

  // app-chat is a private service, so the socket authenticates with a key scoped to it alone rather
  // than the gateway access token. Minted per connect through the cache, so a reconnect after the
  // key aged out dials with a fresh one.
  const chatSocketUrl = useCallback(async (): Promise<string> => {
    const api = apiRef.current;
    const connection = api.getConnection();
    if (!connection) throw new Error("Not connected to a Vesta gateway.");
    const key = await api.serviceKeys.get(name, "app-chat");
    return serviceKeySocketUrl(connection.url, name, "app-chat", key, "/ws");
  }, [name]);

  const dropChatKey = useCallback(() => {
    apiRef.current.serviceKeys.drop(name, "app-chat");
  }, [name]);

  const activitySelector = useCallback(
    (tree: Tree | null) => selectAgentActivitySnapshot(tree, active, name),
    [active, name],
  );
  const agentActivity = useOptionalControllerReplica(
    controller,
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
  const pendingNotifications = useOptionalControllerReplica(
    controller,
    pendingSelector,
    idsEqual,
  );

  // ChatState is the model's single source of truth. It lives in a ref (synchronous, so a batch of
  // appends dedups against the running accumulation) mirrored into React state for rendering. It is
  // seeded from the hold so a conversation renders immediately (stale) across a controller epoch
  // instead of blanking to a skeleton; seedTail refetches and merges by id. Every commit persists the
  // render slice back to the hold under the current key, so a background/foreground survives it.
  const [state, setState] = useState<ChatState>(
    () => holds.chat.read(key) ?? initialChatState(),
  );
  const stateRef = useRef<ChatState>(state);
  // The key is captured here, not read from a ref, so a paced-typing timer from a previous
  // agent/gateway epoch can only ever write its own cell, never the next one's.
  const commit = useCallback(
    (fold: (current: ChatState) => ChatState) => {
      stateRef.current = fold(stateRef.current);
      setState(stateRef.current);
      holds.chat.persist(key, stateRef.current);
    },
    [holds, key],
  );

  const [isTyping, setIsTyping] = useState(false);
  const [latestLiveChat, setLatestLiveChat] = useState<string | null>(null);
  // The next paced chat, published when its typing delay starts: the TTS
  // prefetch window, so playback can start the moment the message is shown.
  const [pendingLiveChat, setPendingLiveChat] = useState<string | null>(null);
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

  // Suspended while a voice conversation is open: spoken replies must not sit
  // behind the typing-pacing delay, so delivery flushes immediately.
  const pacingSuspendedRef = useRef(false);
  const setPacingSuspended = useCallback(
    (suspended: boolean) => {
      pacingSuspendedRef.current = suspended;
      if (suspended) flushQueue();
    },
    [flushQueue],
  );

  const drainQueue = useCallback(
    function drainQueue() {
      if (drainingRef.current) return;
      const queue = chatQueueRef.current;
      const next = queue[0];
      if (next === undefined) {
        setIsTyping(false);
        return;
      }
      if (
        queue.length > PACING.flushThreshold ||
        !naturalPacingRef.current ||
        pacingSuspendedRef.current
      ) {
        flushQueue();
        return;
      }
      drainingRef.current = true;
      setIsTyping(true);
      if (next.type === "chat") setPendingLiveChat(next.text);
      const delay = typingDelay(next.type === "chat" ? next.text.length : 0);
      typingTimerRef.current = setTimeout(() => {
        typingTimerRef.current = null;
        queue.shift();
        commit((current) => commitPacedChat(current, next));
        if (next.type === "chat") setLatestLiveChat(next.text);
        drainingRef.current = false;
        drainQueue();
      }, delay);
    },
    [commit, flushQueue],
  );

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
      if (!controller) {
        return Promise.reject(new Error("The gateway is not connected."));
      }
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
    if (!active || !name || !controller) return;
    let cancelled = false;

    // Seed from this key's hold cell (survives the controller epoch and screen pops); a missing
    // cell means a never-visited agent or gateway, which starts empty.
    const seeded = holds.chat.read(key) ?? initialChatState();
    stateRef.current = seeded;
    setState(seeded);
    resetTyping();

    // Reseed the tail from the newest history page and MERGE, never replace. Runs on every socket
    // open (initial connect and each reconnect), so a replay-free gap self-heals, bumping
    // reseedRevision so the notifications page refetches its own history. A failed fetch while the
    // socket stays healthy retries on a capped backoff, so one blip never strands the skeleton.
    const seed = async () => {
      const page = await fetchPage();
      if (cancelled) return;
      commit((current) => seedTail(current, page));
      setReseedRevision((revision) => revision + 1);
    };

    let seedRetryTimer: ReturnType<typeof setTimeout> | null = null;
    let seedRetryDelay = SEED_RETRY_MS;
    let socketOpen = false;
    const clearSeedRetry = () => {
      if (seedRetryTimer) clearTimeout(seedRetryTimer);
      seedRetryTimer = null;
    };
    const runSeed = () => {
      void seed()
        .then(() => {
          seedRetryDelay = SEED_RETRY_MS;
        })
        .catch((error: unknown) => {
          console.warn("chat: history load failed", error);
          // Retries are scoped to a healthy open socket; a fetch that fails after the
          // socket closed must not keep polling history, the next open reseeds instead.
          if (cancelled || !socketOpen) return;
          seedRetryTimer = setTimeout(() => {
            seedRetryTimer = null;
            runSeed();
          }, seedRetryDelay);
          seedRetryDelay = Math.min(seedRetryDelay * 2, SEED_RETRY_MAX_MS);
        });
    };

    const addLiveEvent = (event: ChatMessage) => {
      const { state: next, paced } = foldLiveEvent(stateRef.current, event);
      commit(() => next);
      if (paced) enqueueChat(event);
    };

    const socket = createChatSocket(
      {
        buildUrl: chatSocketUrl,
        createSocket: createRnSocket,
        setTimer: (fn, ms) => setTimeout(fn, ms) as unknown as number,
        clearTimer: (handle) => clearTimeout(handle),
      },
      {
        onEvent: addLiveEvent,
        onClosedBeforeOpen: dropChatKey,
        onStateChange: (socketState) => {
          socketOpen = socketState === "open";
          clearSeedRetry();
          if (socketOpen) {
            resetTyping();
            seedRetryDelay = SEED_RETRY_MS;
            runSeed();
          }
        },
      },
    );

    return () => {
      cancelled = true;
      clearSeedRetry();
      socket.close();
      resetTyping();
    };
  }, [
    active,
    controller,
    name,
    key,
    holds,
    commit,
    resetTyping,
    enqueueChat,
    fetchPage,
    chatSocketUrl,
    dropChatKey,
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
      if (!name || !controller) return false;
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
      if (!name || !controller) return;
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
    if (
      !name ||
      !controller ||
      loadingMoreRef.current ||
      stateRef.current.cursor === null
    ) {
      return;
    }
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await fetchPage(stateRef.current.cursor);
      commit((current) => prependPage(current, page.events, page.cursor));
    } catch (error) {
      // hasMore stays truthy, so the next onEndReached retries the page naturally.
      console.warn("chat: history page load failed", error);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [name, controller, fetchPage, commit]);

  // Memoized so the AgentContext value built on top of it only changes identity when a consumed
  // field does; otherwise every provider render would re-render all four agent pages.
  return useMemo(
    () => ({
      events: state.messages,
      agentState: agentActivity.state,
      agentStateReady: agentActivity.ready,
      isTyping,
      connected,
      historyLoaded: state.historyLoaded,
      pendingNotifications,
      latestLiveChat,
      pendingLiveChat,
      hasMore,
      loadingMore,
      loadMore,
      send,
      retry,
      reseedRevision,
      setPacingSuspended,
    }),
    [
      state.messages,
      state.historyLoaded,
      agentActivity.state,
      agentActivity.ready,
      isTyping,
      connected,
      pendingNotifications,
      latestLiveChat,
      pendingLiveChat,
      hasMore,
      loadingMore,
      loadMore,
      send,
      retry,
      reseedRevision,
      setPacingSuspended,
    ],
  );
}
