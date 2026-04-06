import { useCallback, useEffect, useRef, useState } from "react";
import type { VestaEvent, AgentActivityState } from "@/lib/types";
import { wsChatUrl, fetchHistory } from "@/lib/connection";
import { useAuth } from "@/providers/AuthProvider";
import { useSpeech } from "@/hooks/use-speech";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

// Module-level sender so non-descendant components (Settings, etc.) can push
// typed events over the already-open chat WebSocket without opening their
// own connection.
let activeSender: ((event: object) => boolean) | null = null;
export function sendChatEvent(event: object): boolean {
  return activeSender ? activeSender(event) : false;
}

export function useChat(name: string | null, active: boolean, speechEnabled: boolean) {
  const { setReachable } = useAuth();
  const { speak, isSpeaking, stop: stopSpeech } = useSpeech(name, speechEnabled);
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [connected, setConnected] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pendingEchoesRef = useRef<string[]>([]);
  const cursorRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active || !name) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = RECONNECT_BASE;

    setMessages([]);
    cursorRef.current = null;
    pendingEchoesRef.current = [];

    const doConnect = () => {
      if (cancelled) return;

      let url: string;
      try {
        url = wsChatUrl(name);
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
        setReachable(true);
        setMessages([]);
        cursorRef.current = null;
        pendingEchoesRef.current = [];
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
          setMessages((prev) => {
            const updated = [...prev, event];
            return updated.length > MAX_MESSAGES
              ? updated.slice(-MAX_MESSAGES)
              : updated;
          });
          if (event.type === "chat" && event.text) {
            speak(event.text);
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
        setReachable(false);
        reconnectTimer = setTimeout(doConnect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
      };

      socket.onerror = () => { };
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
    };
  }, [active, name]);

  const send = useCallback((text: string): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "message", text }));
    pendingEchoesRef.current.push(text);
    setMessages((prev) => {
      const updated: VestaEvent[] = [...prev, { type: "user", text, ts: new Date().toISOString() }];
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
    return () => { activeSender = null; };
  }, [sendEvent]);

  const hasMore = cursorRef.current !== null;

  const loadMore = useCallback(async () => {
    const cursor = cursorRef.current;
    if (!name || loadingMore || cursor === null) return;

    setLoadingMore(true);
    try {
      const result = await fetchHistory(name, cursor);
      const events = result.events ?? [];
      setMessages((prev) => [...events, ...prev]);
      cursorRef.current = result.cursor;
    } finally {
      setLoadingMore(false);
    }
  }, [name, loadingMore]);

  return { messages, agentState, connected, hasMore, loadingMore, loadMore, send, sendEvent, isSpeaking, stopSpeech };
}
