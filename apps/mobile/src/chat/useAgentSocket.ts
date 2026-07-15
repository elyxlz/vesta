import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import type {
  AgentActivityState,
  InputMethod,
  VestaEvent,
} from "@/api/types";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

const MAX_EVENTS = 5000;
const RECONNECT_MAX_MS = 30_000;
const TYPING_DELAY_PER_CHARACTER_MS = 25;
const TYPING_DELAY_MIN_MS = 1500;
const TYPING_DELAY_MAX_MS = 6000;
const TYPING_DELAY_VARIANCE = 0.2;

function capped(events: VestaEvent[]): VestaEvent[] {
  return events.length > MAX_EVENTS ? events.slice(-MAX_EVENTS) : events;
}

function typingDelay(characterCount: number): number {
  const base = Math.min(
    TYPING_DELAY_MIN_MS + TYPING_DELAY_PER_CHARACTER_MS * characterCount,
    TYPING_DELAY_MAX_MS,
  );
  const variance = Math.floor(base * TYPING_DELAY_VARIANCE);
  return base + Math.floor(Math.random() * variance * 2) - variance;
}

export function useAgentSocket(name: string, active: boolean) {
  const { api } = useSession();
  const { naturalChatPacing } = usePreferences();
  const [events, setEvents] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [isTyping, setIsTyping] = useState(false);
  const [connected, setConnected] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [pendingNotifications, setPendingNotifications] = useState<string[]>([]);
  const [snapshotRevision, setSnapshotRevision] = useState(0);
  const [latestLiveChat, setLatestLiveChat] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cursor, setCursor] = useState<number | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const pendingEchoesRef = useRef<string[]>([]);
  const chatQueueRef = useRef<VestaEvent[]>([]);
  const drainingChatQueueRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const naturalChatPacingRef = useRef(naturalChatPacing);
  naturalChatPacingRef.current = naturalChatPacing;

  const append = useCallback((event: VestaEvent) => {
    setEvents((current) => capped([...current, event]));
  }, []);

  const clearTypingTimer = useCallback(() => {
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = null;
  }, []);

  const resetTyping = useCallback(() => {
    clearTypingTimer();
    chatQueueRef.current = [];
    drainingChatQueueRef.current = false;
    setIsTyping(false);
  }, [clearTypingTimer]);

  const flushChatQueue = useCallback(() => {
    clearTypingTimer();
    const queued = chatQueueRef.current;
    chatQueueRef.current = [];
    drainingChatQueueRef.current = false;
    for (const event of queued) {
      append(event);
      if (event.type === "chat") setLatestLiveChat(event.text);
    }
    setIsTyping(false);
  }, [append, clearTypingTimer]);

  const drainChatQueue = useCallback(function drainChatQueue() {
    if (drainingChatQueueRef.current) return;
    const queue = chatQueueRef.current;
    if (queue.length === 0) {
      setIsTyping(false);
      return;
    }
    if (queue.length > 3 || !naturalChatPacingRef.current) {
      flushChatQueue();
      return;
    }

    const next = queue[0];
    if (!next) return;
    drainingChatQueueRef.current = true;
    setIsTyping(true);
    const delay = typingDelay(next.type === "chat" ? next.text.length : 0);
    typingTimerRef.current = setTimeout(() => {
      typingTimerRef.current = null;
      queue.shift();
      append(next);
      if (next.type === "chat") setLatestLiveChat(next.text);
      drainingChatQueueRef.current = false;
      drainChatQueue();
    }, delay);
  }, [append, flushChatQueue]);

  const enqueueChatMessage = useCallback(
    (event: VestaEvent) => {
      chatQueueRef.current.push(event);
      drainChatQueue();
    },
    [drainChatQueue],
  );

  useEffect(() => {
    if (!naturalChatPacing) flushChatQueue();
  }, [flushChatQueue, naturalChatPacing]);

  useEffect(() => {
    if (!active) {
      resetTyping();
      return;
    }
    let mounted = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = 750;
    let appActive = AppState.currentState === "active";

    const close = () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      socket?.close();
      socket = null;
      socketRef.current = null;
      setConnected(false);
    };

    const scheduleReconnect = () => {
      if (!mounted || !appActive || reconnectTimer) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    };

    const handleEvent = (event: VestaEvent) => {
      if (event.type === "snapshot") {
        resetTyping();
        setEvents(capped(event.chat.events));
        setAgentState(event.state);
        setPendingNotifications(event.notifications.pending);
        setSnapshotRevision((current) => current + 1);
        setCursor(event.chat.cursor);
        pendingEchoesRef.current = [];
        setHistoryLoaded(true);
        return;
      }
      if (event.type === "user") {
        const echoIndex = pendingEchoesRef.current.indexOf(event.text);
        if (echoIndex !== -1) {
          pendingEchoesRef.current.splice(echoIndex, 1);
          return;
        }
      }
      if (event.type === "status") setAgentState(event.state);
      if (event.type === "notification_cleared") {
        setPendingNotifications((current) =>
          current.filter((identifier) => identifier !== event.notif_id),
        );
      }
      if (event.type === "chat") {
        enqueueChatMessage(event);
      } else {
        append(event);
        if (event.type === "error" || event.type === "rate_limited") {
          resetTyping();
        }
      }
    };

    const connect = () => {
      if (!mounted || !appActive || socket) return;
      const next = new WebSocket(
        api.websocketUrl(`/agents/${encodeURIComponent(name)}/ws`),
      );
      socket = next;
      socketRef.current = next;
      next.onopen = () => {
        reconnectDelay = 750;
        setConnected(true);
        setHistoryLoaded(false);
      };
      next.onmessage = (message) => {
        if (typeof message.data !== "string") return;
        try {
          const event: VestaEvent = JSON.parse(message.data);
          handleEvent(event);
        } catch {
          // Ignore one malformed agent frame without dropping the stream.
        }
      };
      next.onerror = () => next.close();
      next.onclose = () => {
        if (socket === next) socket = null;
        if (socketRef.current === next) socketRef.current = null;
        setConnected(false);
        setAgentState("idle");
        resetTyping();
        scheduleReconnect();
      };
    };

    const appStateSubscription = AppState.addEventListener("change", (state) => {
      appActive = state === "active";
      if (appActive) connect();
      else close();
    });
    connect();

    return () => {
      mounted = false;
      appStateSubscription.remove();
      resetTyping();
      close();
    };
  }, [active, api, append, enqueueChatMessage, name, resetTyping]);

  const sendEvent = useCallback((event: Record<string, unknown>): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(event));
    return true;
  }, []);

  const send = useCallback(
    (text: string, inputMethod: InputMethod = "typed"): boolean => {
      if (!sendEvent({ type: "message", text, input_method: inputMethod })) {
        return false;
      }
      pendingEchoesRef.current.push(text);
      append({
        type: "user",
        text,
        input_method: inputMethod,
        ts: new Date().toISOString(),
      });
      return true;
    },
    [append, sendEvent],
  );

  const loadMore = useCallback(async (): Promise<void> => {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    try {
      const parameters = new URLSearchParams({
        channel: "app-chat",
        cursor: String(cursor),
      });
      const response = await api.json<{
        events: VestaEvent[];
        cursor: number | null;
      }>(
        `/agents/${encodeURIComponent(name)}/history?${parameters.toString()}`,
      );
      setEvents((current) => [...response.events, ...current]);
      setCursor(response.cursor);
    } finally {
      setLoadingMore(false);
    }
  }, [api, cursor, loadingMore, name]);

  return {
    events,
    agentState,
    isTyping,
    connected,
    historyLoaded,
    pendingNotifications,
    snapshotRevision,
    latestLiveChat,
    hasMore: cursor !== null,
    loadingMore,
    loadMore,
    send,
    sendEvent,
  };
}
