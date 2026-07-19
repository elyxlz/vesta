import { useCallback, useEffect, useRef, useState } from "react";
import type { VestaEvent, InputMethod } from "@/lib/types";
import type { Delta, Tree } from "@vesta/core";
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

function capTail(messages: VestaEvent[]): VestaEvent[] {
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
  const [messages, setMessages] = useState<VestaEvent[]>([]);
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
  const chatQueueRef = useRef<VestaEvent[]>([]);
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
    (event: VestaEvent) => {
      chatQueueRef.current.push(event);
      drainQueue();
    },
    [drainQueue],
  );

  const markIntent = useCallback(
    (intentId: string, state: "retry" | "failed") => {
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

    // Reseed the tail from the newest history page, dropping any prior live buffer. Serves both the
    // initial load and a resync (the id set is rebuilt, so later appends dedup against it).
    const seedTail = async () => {
      const page = await fetchHistory(agent, "app-chat");
      if (cancelled) return;
      shownIdsRef.current = new Set(
        page.events.flatMap((e) => (e.id != null ? [e.id] : [])),
      );
      setCursor(page.cursor);
      setMessages(capTail(page.events));
      setHistoryLoaded(true);
    };

    // Fold one live event into the tail: confirm an optimistic bubble by intent id, dedup a persisted
    // row by event id, pace chat through the typing queue, append everything else.
    const addLiveEvent = (event: VestaEvent) => {
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
        const events: VestaEvent[] = delta.events;
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
      const agent = name;
      const intent = createSendMessageIntent(
        agent,
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
      void controller.http
        .json(`/agents/${encodeURIComponent(agent)}/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...intent.body, intent_id: intent.id }),
        })
        .catch((error: unknown) => {
          // A 200 only means queued-on-tap; delivery truth is the append echo. A retryable 503 keeps
          // the bubble as retryable; anything else marks it failed.
          if (error instanceof ApiError && error.status === 503)
            markIntent(intent.id, "retry");
          else markIntent(intent.id, "failed");
        });
      return true;
    },
    [controller, name, markIntent],
  );

  const hasMore = cursor !== null;

  const loadMore = useCallback(async () => {
    if (!name || loadingMoreRef.current || cursor === null) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const result = await fetchHistory(name, "app-chat", cursor);
      for (const event of result.events)
        if (event.id != null) shownIdsRef.current.add(event.id);
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
  };
}
