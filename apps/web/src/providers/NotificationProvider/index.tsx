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
import {
  connectReconnectingWs,
  type ReconnectingWsHandle,
} from "@/lib/reconnecting-ws";
import { isTauri } from "@/lib/env";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { router } from "@/router";
import type { AgentInfo, VestaEvent } from "@/lib/types";

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

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { agents, reachable } = useGateway();
  const focused = useWindowFocus();
  const focusedRef = useRef(focused);
  useEffect(() => {
    focusedRef.current = focused;
  }, [focused]);

  const permissionRef = useRef<boolean>(false);
  const tapsRef = useRef<Map<string, ReconnectingWsHandle>>(new Map());
  const chattingAgentRef = useRef<string | null>(null);
  const prevStatusRef = useRef<Map<string, AgentInfo["status"]>>(new Map());

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
      const handle = connectReconnectingWs({
        url: () => wsUrl(name, { skipHistory: true }),
        onMessage: (data) => {
          let event: VestaEvent;
          try {
            event = JSON.parse(data) as VestaEvent;
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
        },
      });
      tapsRef.current.set(name, handle);
    }

    function closeTap(name: string) {
      const handle = tapsRef.current.get(name);
      if (!handle) return;
      handle.close();
      tapsRef.current.delete(name);
    }
  }, [aliveKey, reachable, notifyAssistant]);

  useEffect(() => {
    const taps = tapsRef.current;
    return () => {
      for (const handle of taps.values()) handle.close();
      taps.clear();
    };
  }, []);

  useEffect(() => {
    for (const agent of agents) {
      const previous = prevStatusRef.current.get(agent.name);
      prevStatusRef.current.set(agent.name, agent.status);
      if (!previous || previous === agent.status) continue;
      if (agent.status !== "not_authenticated") continue;
      if (!permissionRef.current) continue;
      try {
        const n = new Notification(`${agent.name} needs to sign in again`, {
          body: "Vesta lost its Claude credentials. Tap to re-authenticate.",
          tag: `${agent.name}-not-authenticated`,
        });
        n.onclick = () => {
          void focusAndNavigate(agent.name);
          n.close();
        };
      } catch {
        /* ignore */
      }
    }
  }, [agents]);

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
