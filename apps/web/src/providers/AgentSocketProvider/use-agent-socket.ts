import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ChatMessage,
  ChatState,
  InputMethod,
  SendFailure,
  Tree,
} from "@vesta/core";
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
  trimTail,
  typingDelay,
} from "@vesta/core";
import { useController } from "@/providers/ControllerProvider";
import { useReplica, useSyncState } from "@vesta/core/react";
import { createBrowserSocket } from "@/providers/ControllerProvider/browser-socket";
import { websocketUrl } from "@/lib/authed-url";
import { fetchHistory } from "@/api/agents";
import { useChatPacing } from "@/stores/use-chat-pacing";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

interface UseAgentSocketOptions {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
  onPrefetch?: (text: string) => void;
}

// The chat view-model over the core controller and the shared chat-stream model. The chat tail is a
// per-agent app-chat socket (replay-free: it streams only events appended after connect) joined to
// the HTTP history page, deduped at the seam by event id; the hook fetches the tail at mount, in
// parallel with the socket handshake, and refetches it on every reconnect open so a gap self-heals.
// agentState + pending come from the replica; gateway
// connectedness from the single sync socket. Sends are POST intents confirmed by their chat-socket
// echo. ChatState (mirrored into React state for rendering) is the single source of truth; every fold
// runs synchronously against the ref so a batch of appends dedups against the running accumulation.
export function useAgentSocketState({
  name,
  active,
  onAssistantMessage,
  onPrefetch,
}: UseAgentSocketOptions) {
  const controller = useController();

  const [state, setState] = useState<ChatState>(initialChatState);
  const stateRef = useRef<ChatState>(state);
  const commit = useCallback((fold: (current: ChatState) => ChatState) => {
    stateRef.current = fold(stateRef.current);
    setState(stateRef.current);
  }, []);

  const [isTyping, setIsTyping] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);

  const onAssistantMessageRef = useRef(onAssistantMessage);
  onAssistantMessageRef.current = onAssistantMessage;
  const onPrefetchRef = useRef(onPrefetch);
  onPrefetchRef.current = onPrefetch;
  const chatQueueRef = useRef<ChatMessage[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connected = useSyncState(controller) === "open";

  const activitySelector = useCallback(
    (tree: Tree | null) =>
      name ? (tree?.agents[name]?.info.activityState ?? "idle") : "idle",
    [name],
  );
  const agentState = useReplica(controller.replica, activitySelector);

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      name
        ? (tree?.agents[name]?.notifications.pending ?? []).flatMap((n) =>
            n.notif_id ? [n.notif_id] : [],
          )
        : [],
    [name],
  );
  const pendingNotifications = useReplica(
    controller.replica,
    pendingSelector,
    idsEqual,
  );

  const flushQueue = useCallback(() => {
    for (const event of chatQueueRef.current) {
      commit((current) => commitPacedChat(current, event));
      if (event.type === "chat") onAssistantMessageRef.current?.(event.text);
    }
    chatQueueRef.current = [];
    drainingRef.current = false;
    setIsTyping(false);
  }, [commit]);

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
        !useChatPacing.getState().natural
      ) {
        flushQueue();
        return;
      }
      drainingRef.current = true;
      setIsTyping(true);
      const text = next.type === "chat" ? next.text : undefined;
      if (text) onPrefetchRef.current?.(text);
      const delay = typingDelay(text?.length ?? 0);
      typingTimerRef.current = setTimeout(() => {
        queue.shift();
        commit((current) => commitPacedChat(current, next));
        if (text) onAssistantMessageRef.current?.(text);
        drainingRef.current = false;
        drainQueue();
      }, delay);
    },
    [commit, flushQueue],
  );

  const enqueueChatMessage = useCallback(
    (event: ChatMessage) => {
      chatQueueRef.current.push(event);
      drainQueue();
    },
    [drainQueue],
  );

  // Reflect the send POST's settled disposition into the bubble. A null outcome means queued-on-tap:
  // delivery truth is the append echo (which clears send_state), so only a failure marks the bubble.
  const applyOutcome = useCallback(
    (intentId: string, outcome: Promise<SendFailure | null>) => {
      void outcome.then((failure) => {
        if (failure) commit((current) => markSend(current, intentId, failure));
      });
    },
    [commit],
  );

  useEffect(() => {
    if (!active || !name) return;
    const agent = name;
    let cancelled = false;

    const resetTyping = () => {
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      typingTimerRef.current = null;
      chatQueueRef.current = [];
      drainingRef.current = false;
      setIsTyping(false);
    };

    stateRef.current = initialChatState();
    setState(stateRef.current);
    resetTyping();

    // Reseed the tail from the newest history page and MERGE, never replace. Runs at mount, in
    // parallel with the socket handshake (the fetch needs only the Bearer header, so nothing
    // gates it), and again on each reconnect open so a replay-free gap self-heals; the shared
    // model dedups by id and reconciles pending sends against the page.
    const seed = async () => {
      const page = await fetchHistory(agent, "app-chat");
      if (cancelled) return;
      commit((current) => seedTail(current, page));
    };

    let mountSeedSucceeded = false;
    let sawOpen = false;
    const runSeed = (onSuccess?: () => void) => {
      void seed()
        .then(onSuccess)
        .catch((err: unknown) => {
          console.warn("chat: history load failed", err);
        });
    };
    runSeed(() => {
      mountSeedSucceeded = true;
    });

    const addLiveEvent = (event: ChatMessage) => {
      const { state: next, paced } = foldLiveEvent(stateRef.current, event);
      commit(() => next);
      if (paced) enqueueChatMessage(event);
    };

    const socket = createChatSocket(
      {
        buildUrl: () =>
          websocketUrl(`/agents/${encodeURIComponent(agent)}/app-chat/ws`),
        createSocket: createBrowserSocket,
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (handle) => window.clearTimeout(handle),
      },
      {
        onEvent: addLiveEvent,
        onStateChange: (socketState) => {
          if (socketState === "open") {
            resetTyping();
            // The first open skips the refetch the mount seed already landed; every later open
            // reseeds, and a first open racing a still-inflight mount seed reseeds too, so a
            // mount fetch that fails after this check cannot strand the tail.
            if (sawOpen || !mountSeedSucceeded) runSeed();
            sawOpen = true;
          }
        },
      },
    );

    return () => {
      cancelled = true;
      socket.close();
      resetTyping();
    };
  }, [active, name, commit, enqueueChatMessage]);

  const send = useCallback(
    (text: string, inputMethod: InputMethod = "typed"): boolean => {
      if (!name) return false;
      const { id, outcome } = sendMessage(
        controller.http,
        name,
        { text, input_method: inputMethod },
        () => crypto.randomUUID(),
      );
      commit((current) => beginSend(current, text, inputMethod, id));
      applyOutcome(id, outcome);
      return true;
    },
    [name, controller, commit, applyOutcome],
  );

  // Re-post a failed/retryable bubble under its ORIGINAL intent id (idempotent): the bubble returns to
  // "sending" and confirms on the same echo. Text + input method come from the bubble the user tapped.
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

  // Skipped while a load is in flight: trimming under an unresolved prepend would leave a hole
  // between the landed page and the kept tail.
  const trimHistory = useCallback(() => {
    if (loadingMoreRef.current) return;
    commit((current) => trimTail(current));
  }, [commit]);

  const loadMore = useCallback(async () => {
    if (!name || loadingMoreRef.current || stateRef.current.cursor === null)
      return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await fetchHistory(
        name,
        "app-chat",
        stateRef.current.cursor,
      );
      commit((current) => prependPage(current, page.events, page.cursor));
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [name, commit]);

  return {
    messages: state.messages,
    agentState,
    isTyping,
    connected,
    historyLoaded: state.historyLoaded,
    pendingNotifications,
    hasMore,
    loadingMore,
    loadMore,
    trimHistory,
    send,
    retry,
  };
}
