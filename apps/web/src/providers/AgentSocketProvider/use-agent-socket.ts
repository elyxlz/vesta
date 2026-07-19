import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";
import type { Delta, InputMethod, Tree } from "@vesta/core";
import {
  PACING,
  typingDelay,
  createSendMessageIntent,
  ApiError,
} from "@vesta/core";
import { useController } from "@/providers/ControllerProvider";
import { useReplica, useSyncState, useWatch } from "@vesta/core/react";
import { fetchHistory } from "@/api/agents";
import { useChatPacing } from "@/stores/use-chat-pacing";

function capTail(messages: ChatMessage[]): ChatMessage[] {
  return messages.length > PACING.maxMessages
    ? messages.slice(-PACING.maxMessages)
    : messages;
}

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

interface UseAgentSocketOptions {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
  onPrefetch?: (text: string) => void;
}

// The chat view-model over the core controller. useWatch turns the agent's live edge on;
// controller.subscribeDeltas feeds the chat tail (append/resync are not tree state, so they arrive
// here, not through the replica). agentState + pending come from the replica; connectedness from the
// single sync socket. There is no per-agent WS: the tail is the HTTP history page plus live appends,
// deduped at the seam by event id, and sends are POST intents confirmed by their append echo.
export function useAgentSocketState({
  name,
  active,
  onAssistantMessage,
  onPrefetch,
}: UseAgentSocketOptions) {
  const controller = useController();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cursor, setCursor] = useState<number | null>(null);
  const loadingMoreRef = useRef(false);

  // Ids of persisted events already in `messages`, so a live append that races the history fetch
  // (or a resync refetch) never duplicates a row.
  const shownIdsRef = useRef<Set<number>>(new Set());
  // Intent ids of optimistic bubbles awaiting their append echo (delivery truth is the echo).
  const pendingIntentsRef = useRef<Set<string>>(new Set());

  const onAssistantMessageRef = useRef(onAssistantMessage);
  onAssistantMessageRef.current = onAssistantMessage;
  const onPrefetchRef = useRef(onPrefetch);
  onPrefetchRef.current = onPrefetch;
  const chatQueueRef = useRef<ChatMessage[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useWatch(controller, active ? name : null);
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
      setMessages((prev) => capTail([...prev, event]));
      if (event.type === "chat") onAssistantMessageRef.current?.(event.text);
    }
    chatQueueRef.current = [];
    drainingRef.current = false;
    setIsTyping(false);
  }, []);

  const drainQueue = useCallback(() => {
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
      setMessages((prev) => capTail([...prev, next]));
      if (text) onAssistantMessageRef.current?.(text);
      drainingRef.current = false;
      drainQueue();
    }, delay);
  }, [flushQueue]);

  const enqueueChatMessage = useCallback(
    (event: ChatMessage) => {
      chatQueueRef.current.push(event);
      drainQueue();
    },
    [drainQueue],
  );

  const markIntent = useCallback(
    (intentId: string, state: "sending" | "retry" | "failed") => {
      setMessages((prev) =>
        prev.map((m) =>
          m.type === "user" && m.intent_id === intentId
            ? { ...m, send_state: state }
            : m,
        ),
      );
    },
    [],
  );

  // POST the send-message intent. A 200 only means queued-on-tap; delivery truth is the append echo
  // (which clears send_state). A retryable 503 leaves the bubble retryable; any other error fails it.
  // The intent id is idempotent server-side, so a retry re-posts the same id (dedup on the echo).
  const postIntent = useCallback(
    (
      agent: string,
      intentId: string,
      text: string,
      inputMethod: InputMethod,
    ) => {
      void controller.http
        .json(`/agents/${encodeURIComponent(agent)}/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            input_method: inputMethod,
            intent_id: intentId,
          }),
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 503)
            markIntent(intentId, "retry");
          else markIntent(intentId, "failed");
        });
    },
    [controller, markIntent],
  );

  useEffect(() => {
    if (!active || !name) return;
    const agent = name;
    let cancelled = false;

    const resetTyping = () => {
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      chatQueueRef.current = [];
      drainingRef.current = false;
      setIsTyping(false);
    };

    setMessages([]);
    setHistoryLoaded(false);
    setCursor(null);
    shownIdsRef.current = new Set();
    pendingIntentsRef.current = new Set();
    resetTyping();

    // Reseed the tail from the newest history page and MERGE, never replace: a live row that raced the
    // fetch (id absent from the page) and an optimistic bubble still awaiting its echo both survive, so
    // no delivered or in-flight message is dropped. shownIds is UNIONed with the page ids (queued chat
    // and prior appends keep their dedup entries). Serves the initial load and a resync alike.
    const seedTail = async () => {
      const page = await fetchHistory(agent, "app-chat");
      if (cancelled) return;
      const pageIds = new Set<number>(page.events.map((e) => e.id));
      setCursor(page.cursor);
      setMessages((prev) => {
        const survivors = prev.filter(
          (m) =>
            (m.type === "user" &&
              m.intent_id != null &&
              pendingIntentsRef.current.has(m.intent_id)) ||
            (m.id != null && !pageIds.has(m.id)),
        );
        return capTail([...page.events, ...survivors]);
      });
      for (const id of pageIds) shownIdsRef.current.add(id);
      setHistoryLoaded(true);
    };

    // Fold one live event into the tail: confirm an optimistic bubble by intent id, dedup a persisted
    // row by event id, pace chat through the typing queue, append everything else.
    const addLiveEvent = (event: ChatMessage) => {
      if (
        event.type === "user" &&
        event.intent_id != null &&
        pendingIntentsRef.current.has(event.intent_id)
      ) {
        const intentId = event.intent_id;
        pendingIntentsRef.current.delete(intentId);
        if (event.id != null) shownIdsRef.current.add(event.id);
        setMessages((prev) =>
          prev.map((m) =>
            m.type === "user" && m.intent_id === intentId
              ? {
                  ...m,
                  send_state: undefined,
                  id: event.id ?? m.id,
                  ts: event.ts ?? m.ts,
                }
              : m,
          ),
        );
        return;
      }
      if (event.id != null) {
        if (shownIdsRef.current.has(event.id)) return;
        shownIdsRef.current.add(event.id);
      }
      if (event.type === "chat") {
        enqueueChatMessage(event);
      } else {
        setMessages((prev) => capTail([...prev, event]));
        if (event.type === "error" || event.type === "rate_limited")
          resetTyping();
      }
    };

    void seedTail().catch((err: unknown) => {
      console.warn("chat: history load failed", err);
    });

    const unsubscribe = controller.subscribeDeltas((delta: Delta) => {
      if (delta.type === "append" && delta.agent === agent) {
        const events: ChatMessage[] = delta.events;
        for (const event of events) addLiveEvent(event);
      } else if (delta.type === "resync" && delta.agent === agent) {
        resetTyping();
        void seedTail().catch((err: unknown) => {
          console.warn("chat: resync refetch failed", err);
        });
      }
    });

    return () => {
      cancelled = true;
      unsubscribe();
      resetTyping();
    };
  }, [active, name, controller, enqueueChatMessage]);

  const send = useCallback(
    (text: string, inputMethod: InputMethod = "typed"): boolean => {
      if (!name) return false;
      const intent = createSendMessageIntent(
        name,
        { text, input_method: inputMethod },
        () => crypto.randomUUID(),
      );
      pendingIntentsRef.current.add(intent.id);
      setMessages((prev) =>
        capTail([
          ...prev,
          {
            type: "user",
            text,
            input_method: inputMethod,
            intent_id: intent.id,
            send_state: "sending",
            ts: new Date().toISOString(),
          },
        ]),
      );
      postIntent(name, intent.id, text, inputMethod);
      return true;
    },
    [name, postIntent],
  );

  // Re-post a failed/retryable bubble under its ORIGINAL intent id (idempotent): the bubble returns to
  // "sending" and confirms on the same echo. Text + input method come from the bubble the user tapped.
  const retry = useCallback(
    (intentId: string, text: string, inputMethod: InputMethod = "typed") => {
      if (!name) return;
      pendingIntentsRef.current.add(intentId);
      markIntent(intentId, "sending");
      postIntent(name, intentId, text, inputMethod);
    },
    [name, markIntent, postIntent],
  );

  const hasMore = cursor !== null;

  const loadMore = useCallback(async () => {
    if (!name || loadingMoreRef.current || cursor === null) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const result = await fetchHistory(name, "app-chat", cursor);
      for (const event of result.events) shownIdsRef.current.add(event.id);
      setMessages((prev) => [...result.events, ...prev]);
      setCursor(result.cursor);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [name, cursor]);

  return {
    messages,
    agentState,
    isTyping,
    connected,
    historyLoaded,
    pendingNotifications,
    hasMore,
    loadingMore,
    loadMore,
    send,
    retry,
  };
}
