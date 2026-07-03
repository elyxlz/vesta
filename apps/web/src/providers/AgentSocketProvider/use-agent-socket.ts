import { useCallback, useEffect, useRef, useState } from "react";
import type { VestaEvent, AgentActivityState, InputMethod } from "@/lib/types";
import { wsUrl, fetchHistory } from "@/lib/connection";
import {
  connectReconnectingWs,
  type ReconnectingWsHandle,
} from "@/lib/reconnecting-ws";
import { useChatPacing } from "@/stores/use-chat-pacing";

const MAX_MESSAGES = 5000;

const TYPING_DELAY_PER_CHAR = 25;
const TYPING_DELAY_MIN = 1500;
const TYPING_DELAY_MAX = 6000;
const TYPING_VARIANCE = 0.2;

function capTail(messages: VestaEvent[]): VestaEvent[] {
  return messages.length > MAX_MESSAGES
    ? messages.slice(-MAX_MESSAGES)
    : messages;
}

function typingDelay(charCount: number): number {
  const raw = Math.min(
    TYPING_DELAY_MIN + TYPING_DELAY_PER_CHAR * charCount,
    TYPING_DELAY_MAX,
  );
  const variance = Math.floor(raw * TYPING_VARIANCE);
  return raw + Math.floor(Math.random() * variance * 2) - variance;
}

interface UseAgentSocketOptions {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
  onPrefetch?: (text: string) => void;
}

export function useAgentSocketState({
  name,
  active,
  onAssistantMessage,
  onPrefetch,
}: UseAgentSocketOptions) {
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  // Live preview of the in-progress extended-thinking block, accumulated from thinking_delta
  // events. Cleared when the turn's visible output lands (the complete block is the record).
  const [liveThinking, setLiveThinking] = useState("");
  // Live draft of the reply the agent is typing into `app-chat send`, accumulated from
  // chat_delta events. Replaced by the real chat bubble the moment it arrives.
  const [liveReply, setLiveReply] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [connected, setConnected] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  // Pending-notification ids from the latest connect snapshot — the authoritative seed the
  // notifications view derives pending state from (then maintains live via notification_cleared).
  const [pendingNotifications, setPendingNotifications] = useState<string[]>(
    [],
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);

  const wsRef = useRef<ReconnectingWsHandle | null>(null);
  const liveThinkingRef = useRef("");
  const liveThinkingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const liveReplyRef = useRef("");
  const liveReplyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingEchoesRef = useRef<string[]>([]);
  const cursorRef = useRef<number | null>(null);
  const onAssistantMessageRef = useRef(onAssistantMessage);
  onAssistantMessageRef.current = onAssistantMessage;
  const onPrefetchRef = useRef(onPrefetch);
  onPrefetchRef.current = onPrefetch;
  const chatQueueRef = useRef<VestaEvent[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Deltas arrive many times a second; batch them into one state update per frame-ish tick so
  // a long thinking stretch doesn't re-render the chat per chunk.
  const appendLiveThinking = useCallback((text: string) => {
    liveThinkingRef.current += text;
    if (liveThinkingTimerRef.current) return;
    liveThinkingTimerRef.current = setTimeout(() => {
      liveThinkingTimerRef.current = null;
      setLiveThinking(liveThinkingRef.current);
    }, 150);
  }, []);

  const clearLiveThinking = useCallback(() => {
    if (liveThinkingTimerRef.current) {
      clearTimeout(liveThinkingTimerRef.current);
      liveThinkingTimerRef.current = null;
    }
    liveThinkingRef.current = "";
    setLiveThinking("");
  }, []);

  const appendLiveReply = useCallback((text: string, reset: boolean) => {
    liveReplyRef.current = reset ? text : liveReplyRef.current + text;
    if (liveReplyTimerRef.current) return;
    liveReplyTimerRef.current = setTimeout(() => {
      liveReplyTimerRef.current = null;
      setLiveReply(liveReplyRef.current);
    }, 150);
  }, []);

  const clearLiveReply = useCallback(() => {
    if (liveReplyTimerRef.current) {
      clearTimeout(liveReplyTimerRef.current);
      liveReplyTimerRef.current = null;
    }
    liveReplyRef.current = "";
    setLiveReply("");
  }, []);

  const flushQueue = useCallback(() => {
    for (const event of chatQueueRef.current) {
      setMessages((prev) => capTail([...prev, event]));
      if (event.type === "chat") {
        onAssistantMessageRef.current?.(event.text);
      }
    }
    chatQueueRef.current = [];
    drainingRef.current = false;
    setIsTyping(false);
  }, []);

  const drainQueue = useCallback(() => {
    if (drainingRef.current) return;
    const queue = chatQueueRef.current;
    if (queue.length === 0) {
      setIsTyping(false);
      return;
    }
    if (queue.length > 3 || !useChatPacing.getState().natural) {
      flushQueue();
      return;
    }
    const next = queue[0];
    drainingRef.current = true;
    setIsTyping(true);
    const text = next.type === "chat" ? next.text : undefined;
    if (text) onPrefetchRef.current?.(text);
    const delay = typingDelay(text?.length ?? 0);
    typingTimerRef.current = setTimeout(() => {
      queue.shift();
      setMessages((prev) => capTail([...prev, next]));
      if (text) {
        onAssistantMessageRef.current?.(text);
      }
      drainingRef.current = false;
      drainQueue();
    }, delay);
  }, [flushQueue]);

  const enqueueChatMessage = useCallback(
    (event: VestaEvent, opts?: { immediate: boolean }) => {
      chatQueueRef.current.push(event);
      if (opts?.immediate) {
        if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
        flushQueue();
        return;
      }
      drainQueue();
    },
    [drainQueue, flushQueue],
  );

  useEffect(() => {
    if (!active || !name) return;

    const resetTyping = () => {
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      chatQueueRef.current = [];
      drainingRef.current = false;
      setIsTyping(false);
    };

    const resetConnection = () => {
      setMessages([]);
      setHistoryLoaded(false);
      cursorRef.current = null;
      pendingEchoesRef.current = [];
      resetTyping();
      clearLiveThinking();
      clearLiveReply();
    };

    resetConnection();

    const handle = connectReconnectingWs({
      url: () => wsUrl(name),
      onOpen: () => {
        setConnected(true);
        resetConnection();
      },
      onMessage: (data) => {
        try {
          const event = JSON.parse(data) as VestaEvent;
          if (event.type === "snapshot") {
            setMessages(capTail(event.chat.events));
            cursorRef.current = event.chat.cursor;
            setHistoryLoaded(true);
            setAgentState(event.state);
            setPendingNotifications(event.notifications.pending);
            return;
          }
          if (event.type === "user") {
            const idx = pendingEchoesRef.current.indexOf(event.text);
            if (idx !== -1) {
              pendingEchoesRef.current.splice(idx, 1);
              return;
            }
          }
          if (event.type === "thinking_delta") {
            appendLiveThinking(event.text);
            return;
          }
          if (event.type === "chat_delta") {
            appendLiveReply(event.text, event.reset);
            return;
          }
          // The turn's visible output (or the finished block itself) supersedes the preview.
          if (
            event.type === "thinking" ||
            event.type === "assistant" ||
            event.type === "chat" ||
            (event.type === "status" && event.state === "idle")
          ) {
            clearLiveThinking();
          }
          if (event.type === "chat") {
            // A streamed draft already showed this reply forming; the typing-pacing
            // simulation would only delay the committed bubble behind its own preview.
            const hadDraft = liveReplyRef.current !== "";
            clearLiveReply();
            enqueueChatMessage(event, { immediate: hadDraft });
          } else {
            setMessages((prev) => capTail([...prev, event]));
          }
          if (event.type === "status") {
            setAgentState(event.state);
          }
        } catch (err) {
          console.warn("ws: bad message", err);
        }
      },
      onClose: () => {
        setConnected(false);
        setAgentState("idle");
      },
    });
    wsRef.current = handle;

    return () => {
      handle.close();
      wsRef.current = null;
      setConnected(false);
      resetTyping();
      clearLiveThinking();
      clearLiveReply();
    };
  }, [
    active,
    name,
    appendLiveThinking,
    clearLiveThinking,
    appendLiveReply,
    clearLiveReply,
  ]);

  const sendEvent = useCallback((event: object): boolean => {
    const ws = wsRef.current?.current();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(event));
    return true;
  }, []);

  const send = useCallback(
    (text: string, inputMethod: InputMethod = "typed"): boolean => {
      if (!sendEvent({ type: "message", text, input_method: inputMethod }))
        return false;
      pendingEchoesRef.current.push(text);
      setMessages((prev) =>
        capTail([
          ...prev,
          {
            type: "user",
            text,
            input_method: inputMethod,
            ts: new Date().toISOString(),
          },
        ]),
      );
      return true;
    },
    [sendEvent],
  );

  const hasMore = cursorRef.current !== null;

  const loadMore = useCallback(async () => {
    const cursor = cursorRef.current;
    if (!name || loadingMoreRef.current || cursor === null) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const result = await fetchHistory(name, "app-chat", cursor);
      const events = result.events ?? [];
      setMessages((prev) => [...events, ...prev]);
      cursorRef.current = result.cursor;
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [name]);

  return {
    messages,
    agentState,
    liveThinking,
    liveReply,
    isTyping,
    connected,
    historyLoaded,
    pendingNotifications,
    hasMore,
    loadingMore,
    loadMore,
    send,
    sendEvent,
  };
}
