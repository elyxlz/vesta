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

// Module-level sender so non-descendant components (Settings, etc.) can push
// typed events over the already-open chat WebSocket without opening their
// own connection.
let activeSender: ((event: object) => boolean) | null = null;
export function sendChatEvent(event: object): boolean {
  return activeSender ? activeSender(event) : false;
}

interface UseChatOptions {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
  onPrefetch?: (text: string) => void;
}

export function useChat({
  name,
  active,
  onAssistantMessage,
  onPrefetch,
}: UseChatOptions) {
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [isTyping, setIsTyping] = useState(false);
  const [connected, setConnected] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);

  const wsRef = useRef<ReconnectingWsHandle | null>(null);
  const pendingEchoesRef = useRef<string[]>([]);
  const cursorRef = useRef<number | null>(null);
  const onAssistantMessageRef = useRef(onAssistantMessage);
  onAssistantMessageRef.current = onAssistantMessage;
  const onPrefetchRef = useRef(onPrefetch);
  onPrefetchRef.current = onPrefetch;
  const chatQueueRef = useRef<VestaEvent[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    (event: VestaEvent) => {
      chatQueueRef.current.push(event);
      drainQueue();
    },
    [drainQueue],
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
          if (event.type === "history") {
            setMessages(capTail(event.events));
            cursorRef.current = event.cursor;
            setHistoryLoaded(true);
            if (event.state) setAgentState(event.state);
            return;
          }
          if (event.type === "user") {
            const idx = pendingEchoesRef.current.indexOf(event.text);
            if (idx !== -1) {
              pendingEchoesRef.current.splice(idx, 1);
              return;
            }
          }
          if (event.type === "chat") {
            enqueueChatMessage(event);
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
    };
  }, [active, name]);

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

  useEffect(() => {
    activeSender = sendEvent;
    return () => {
      activeSender = null;
    };
  }, [sendEvent]);

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
    isTyping,
    connected,
    historyLoaded,
    hasMore,
    loadingMore,
    loadMore,
    send,
    sendEvent,
  };
}
