import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useGateway } from "@/providers/GatewayProvider";
import { wsUrl } from "@/lib/connection";
import { isTauri } from "@/lib/env";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { router } from "@/router";
import type { VestaEvent } from "@/lib/types";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const PREVIEW_MAX = 100;
const NOTIFICATION_AUTO_CLOSE_MS = 6000;
const ASKED_KEY = "vesta-notifications-asked";

function truncate(text: string): string {
  return text.length <= PREVIEW_MAX ? text : text.slice(0, PREVIEW_MAX) + "…";
}

async function ensurePermission(): Promise<boolean> {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  if (localStorage.getItem(ASKED_KEY) === "1") return false;
  localStorage.setItem(ASKED_KEY, "1");
  const result = await Notification.requestPermission();
  return result === "granted";
}

async function focusAndNavigate(agentName: string): Promise<void> {
  if (isTauri) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("focus_window");
    } catch {
      /* ignore */
    }
  } else {
    window.focus();
  }
  router.navigate(`/agent/${encodeURIComponent(agentName)}`);
}

interface NotificationContextValue {
  notifyAssistant: (agentName: string, text: string) => void;
  // The agent whose chat the user is actively viewing. Its tap suppresses
  // direct firing so that ChatProvider can instead fire after the UI's
  // typing delay, keeping notification and visible-text in sync.
  setChattingAgent: (agentName: string | null) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(
  null,
);

export function useNotifications(): NotificationContextValue {
  return (
    useContext(NotificationContext) ?? {
      notifyAssistant: () => {},
      setChattingAgent: () => {},
    }
  );
}

interface TapEntry {
  socket: WebSocket | null;
  cancelled: boolean;
  timer: ReturnType<typeof setTimeout> | null;
  delay: number;
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { agents, reachable } = useGateway();
  const focused = useWindowFocus();
  const focusedRef = useRef(focused);
  useEffect(() => {
    focusedRef.current = focused;
  }, [focused]);

  const permissionRef = useRef<boolean>(false);
  const tapsRef = useRef<Map<string, TapEntry>>(new Map());
  const chattingAgentRef = useRef<string | null>(null);

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) {
        setAppBadge(false);
        setFaviconUnseen(false);
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      setAppBadge(false);
      setFaviconUnseen(false);
    };
  }, []);

  const aliveKey = useMemo(
    () =>
      agents
        .filter((a) => a.status === "alive")
        .map((a) => a.name)
        .sort()
        .join("|"),
    [agents],
  );

  const notifyAssistant = useCallback((agentName: string, text: string) => {
    if (focusedRef.current) return;
    if (!permissionRef.current) return;
    const body = text.trim();
    if (!body) return;
    try {
      const n = new Notification(agentName, {
        body: truncate(body),
        tag: agentName,
      });
      const autoClose = setTimeout(() => n.close(), NOTIFICATION_AUTO_CLOSE_MS);
      n.onclick = () => {
        clearTimeout(autoClose);
        void focusAndNavigate(agentName);
        n.close();
      };
      n.onclose = () => clearTimeout(autoClose);
    } catch {
      /* ignore */
    }
  }, []);

  const setChattingAgent = useCallback((agentName: string | null) => {
    chattingAgentRef.current = agentName;
  }, []);

  useEffect(() => {
    let cancelled = false;
    ensurePermission().then((granted) => {
      if (!cancelled) permissionRef.current = granted;
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!reachable) {
      for (const name of Array.from(tapsRef.current.keys())) closeTap(name);
      return;
    }
    const aliveNames = aliveKey ? aliveKey.split("|") : [];
    const aliveSet = new Set(aliveNames);

    for (const name of Array.from(tapsRef.current.keys())) {
      if (!aliveSet.has(name)) closeTap(name);
    }
    for (const name of aliveNames) {
      if (!tapsRef.current.has(name)) openTap(name);
    }

    function openTap(name: string) {
      const entry: TapEntry = {
        socket: null,
        cancelled: false,
        timer: null,
        delay: RECONNECT_BASE_MS,
      };
      tapsRef.current.set(name, entry);

      const connect = () => {
        if (entry.cancelled) return;
        let url: string;
        try {
          url = wsUrl(name, { skipHistory: true });
        } catch {
          entry.timer = setTimeout(connect, entry.delay);
          entry.delay = Math.min(entry.delay * 2, RECONNECT_MAX_MS);
          return;
        }

        const socket = new WebSocket(url);
        entry.socket = socket;

        socket.onopen = () => {
          entry.delay = RECONNECT_BASE_MS;
        };

        socket.onmessage = (e) => {
          if (typeof e.data !== "string") return;
          let event: VestaEvent;
          try {
            event = JSON.parse(e.data) as VestaEvent;
          } catch {
            return;
          }
          if (event.type !== "chat") return;
          if (document.hidden) {
            setAppBadge(true);
            setFaviconUnseen(true);
          }
          // Defer to ChatProvider for the agent being actively chatted with —
          // it fires after the typing delay so notification lines up with UI.
          if (chattingAgentRef.current === name) return;
          notifyAssistant(name, event.text);
        };

        socket.onclose = () => {
          entry.socket = null;
          if (entry.cancelled) return;
          entry.timer = setTimeout(connect, entry.delay);
          entry.delay = Math.min(entry.delay * 2, RECONNECT_MAX_MS);
        };

        socket.onerror = () => {};
      };

      connect();
    }

    function closeTap(name: string) {
      const entry = tapsRef.current.get(name);
      if (!entry) return;
      entry.cancelled = true;
      if (entry.timer) clearTimeout(entry.timer);
      if (entry.socket) {
        entry.socket.onclose = null;
        entry.socket.close();
      }
      tapsRef.current.delete(name);
    }
  }, [aliveKey, reachable, notifyAssistant]);

  useEffect(() => {
    const taps = tapsRef.current;
    return () => {
      for (const entry of taps.values()) {
        entry.cancelled = true;
        if (entry.timer) clearTimeout(entry.timer);
        if (entry.socket) {
          entry.socket.onclose = null;
          entry.socket.close();
        }
      }
      taps.clear();
    };
  }, []);

  const value = useMemo(
    () => ({ notifyAssistant, setChattingAgent }),
    [notifyAssistant, setChattingAgent],
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}
