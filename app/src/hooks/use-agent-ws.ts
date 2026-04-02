import { useCallback, useEffect, useRef, useState } from "react";
import type { VestaEvent, AgentActivityState } from "@/lib/types";
import { wsUrl } from "@/lib/connection";

const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const MAX_MESSAGES = 5000;

export function useAgentWs(name: string | null, active: boolean) {
  const [messages, setMessages] = useState<VestaEvent[]>([]);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const activeRef = useRef(false);
  const nameRef = useRef(name);
  nameRef.current = name;

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const doConnect = useCallback(() => {
    const currentName = nameRef.current;
    if (!currentName || wsRef.current) return;

    let url: string;
    try {
      url = wsUrl(currentName);
    } catch {
      if (activeRef.current) {
        reconnectTimerRef.current = setTimeout(doConnect, reconnectDelayRef.current);
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 2,
          RECONNECT_MAX,
        );
      }
      return;
    }

    const socket = new WebSocket(url);
    wsRef.current = socket;

    socket.onopen = () => {
      reconnectDelayRef.current = RECONNECT_BASE;
      setConnected(true);
      setMessages([]);
    };

    socket.onmessage = (e) => {
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
      wsRef.current = null;
      setConnected(false);
      if (activeRef.current) {
        reconnectTimerRef.current = setTimeout(
          doConnect,
          reconnectDelayRef.current,
        );
        reconnectDelayRef.current = Math.min(
          reconnectDelayRef.current * 2,
          RECONNECT_MAX,
        );
      }
    };

    socket.onerror = (err) => {
      console.warn("ws error:", err);
    };
  }, []);

  useEffect(() => {
    if (active && name) {
      activeRef.current = true;
      setMessages([]);
      reconnectDelayRef.current = RECONNECT_BASE;
      doConnect();
    } else {
      activeRef.current = false;
      cleanup();
    }
    return () => {
      activeRef.current = false;
      cleanup();
    };
  }, [active, name, doConnect, cleanup]);

  const send = useCallback((text: string): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "message", text }));
    return true;
  }, []);

  return { messages, agentState, connected, send };
}
