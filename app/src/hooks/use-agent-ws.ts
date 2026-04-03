import { useEffect, useRef, useState } from "react";
import type { VestaEvent, AgentActivityState } from "@/lib/types";
import { wsUrl } from "@/lib/connection";
import { useAuth } from "@/providers/AuthProvider";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

export function useAgentWs(name: string | null, active: boolean) {
  const { setReachable } = useAuth();
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active || !name) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectDelay = RECONNECT_BASE;

    setMessages([]);

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
        setReachable(true);
        setMessages([]);
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
            if (event.state) setAgentState(event.state);
            return;
          }
          setMessages((prev) => {
            const updated = [...prev, event];
            return updated.length > MAX_MESSAGES
              ? updated.slice(-MAX_MESSAGES)
              : updated;
          });
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
    };
  }, [active, name]);

  const send = (text: string): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "message", text }));
    return true;
  };

  return { messages, agentState, connected, send };
}
