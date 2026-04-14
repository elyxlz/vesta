import { useCallback, useEffect, useRef, useState } from "react";
import type { VestaEvent, AgentActivityState } from "@/lib/types";
import { wsUrl, fetchHistory } from "@/lib/connection";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

const TYPING_DELAY_PER_CHAR = 25;
const TYPING_DELAY_MIN = 1500;
const TYPING_DELAY_MAX = 6000;
const TYPING_VARIANCE = 0.2;

function typingDelay(charCount: number): number {
  const raw = Math.min(TYPING_DELAY_MIN + TYPING_DELAY_PER_CHAR * charCount, TYPING_DELAY_MAX);
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
}

export function useChat({ name, active, onAssistantMessage }: UseChatOptions) {
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [isTyping, setIsTyping] = useState(false);
  const [connected, setConnected] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pendingEchoesRef = useRef<string[]>([]);
  const cursorRef = useRef<number | null>(null);
  const onAssistantMessageRef = useRef(onAssistantMessage);
  onAssistantMessageRef.current = onAssistantMessage;
  const chatQueueRef = useRef<VestaEvent[]>([]);
  const drainingRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushQueue = useCallback(() => {
    for (const event of chatQueueRef.current) {
      setMessages((prev) => {
        const updated = [...prev, event];
        return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
      });
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
    if (queue.length > 3) {
      flushQueue();
      return;
    }
    const next = queue[0];
    drainingRef.current = true;
    setIsTyping(true);
    const text = next.type === "chat" ? next.text : undefined;
    const delay = typingDelay(text?.length ?? 0);
    typingTimerRef.current = setTimeout(() => {
      queue.shift();
      setMessages((prev) => {
        const updated = [...prev, next];
        return updated.length > MAX_MESSAGES ? updated.slice(-MAX_MESSAGES) : updated;
      });
      if (text) {
        onAssistantMessageRef.current?.(text);
      }
      drainingRef.current = false;
      drainQueue();
    }, delay);
  }, [flushQueue]);

  const enqueueChatMessage = useCallback((event: VestaEvent) => {
    chatQueueRef.current.push(event);
    drainQueue();
  }, [drainQueue]);

  useEffect(() => {
    if (!active || !name) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = RECONNECT_BASE;

    setMessages([]);
    setHistoryLoaded(false);
    cursorRef.current = null;
    pendingEchoesRef.current = [];
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    chatQueueRef.current = [];
    drainingRef.current = false;
    setIsTyping(false);

    const doConnect = () => {
      if (cancelled) return;

      let url: string;
      try {
        url = wsUrl(name);
      } catch {
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
        return;
      }

      socket = new WebSocket(url);
      wsRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        reconnectDelay = RECONNECT_BASE;
        setConnected(true);
        setHistoryLoaded(false);
        setMessages([]);
        cursorRef.current = null;
        pendingEchoesRef.current = [];
        if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
        chatQueueRef.current = [];
        drainingRef.current = false;
        setIsTyping(false);
      };

      socket.onmessage = (e) => {
        if (cancelled) return;
        if (typeof e.data !== "string") return;
        try {
          const event = JSON.parse(e.data) as VestaEvent;
          if (event.type === "history") {
            const evts = event.events;
            setMessages(
              evts.length > MAX_MESSAGES ? evts.slice(-MAX_MESSAGES) : evts,
            );
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
            setMessages((prev) => {
              const updated = [...prev, event];
              return updated.length > MAX_MESSAGES
                ? updated.slice(-MAX_MESSAGES)
                : updated;
            });
          }
          if (event.type === "status") {
            setAgentState(event.state);
          }
        } catch (err) {
          console.warn("ws: bad message", err);
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        socket = null;
        wsRef.current = null;
        setConnected(false);
        setAgentState("idle");
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      };

      socket.onerror = () => {};
    };

    doConnect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
      wsRef.current = null;
      setConnected(false);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      chatQueueRef.current = [];
      drainingRef.current = false;
      setIsTyping(false);
    };
  }, [active, name]);

  const send = useCallback((text: string): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "message", text }));
    pendingEchoesRef.current.push(text);
    setMessages((prev) => {
      const updated: VestaEvent[] = [
        ...prev,
        { type: "user", text, ts: new Date().toISOString() },
      ];
      return updated.length > MAX_MESSAGES
        ? updated.slice(-MAX_MESSAGES)
        : updated;
    });
    return true;
  }, []);

  const sendEvent = useCallback((event: object): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(event));
    return true;
  }, []);

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
