import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import { useGateway } from "@/providers/GatewayProvider";
import { wsUrl } from "@/lib/connection";
import {
  connectReconnectingWs,
  type ReconnectingWsHandle,
} from "@/lib/reconnecting-ws";
import { native } from "@/lib/native";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { router } from "@/router";
import type { AgentInfo, VestaEvent } from "@/lib/types";
import { NotificationContext } from "./context";

export { useNotifications } from "./context";

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
  try {
    await native.focusWindow();
  } catch {
    /* ignore */
  }
  router.navigate(`/agent/${encodeURIComponent(agentName)}`);
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

  // Unlike chat previews, a hit rate limit fires even while the app is focused: the chat
  // surface shows nothing for a throttled turn, so this is the user's only signal.
  const notifyRateLimited = useCallback((agentName: string, text: string) => {
    if (!permissionRef.current) return;
    try {
      const n = new Notification(`${agentName} hit a Claude rate limit`, {
        body: text,
        tag: `${agentName}-rate-limited`,
      });
      n.onclick = () => {
        void focusAndNavigate(agentName);
        n.close();
      };
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
          if (event.type === "rate_limited") {
            notifyRateLimited(name, event.text);
            return;
          }
          if (event.type !== "chat") return;
          if (document.hidden) {
            setAppBadge(true);
            setFaviconUnseen(true);
          }
          // Defer to AgentSocketProvider for the agent being actively chatted with —
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
  }, [aliveKey, reachable, notifyAssistant, notifyRateLimited]);

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
      if (
        agent.status !== "not_authenticated" &&
        agent.status !== "unprovisioned"
      )
        continue;
      if (!permissionRef.current) continue;
      const unprovisioned = agent.status === "unprovisioned";
      const title = unprovisioned
        ? `${agent.name} needs to be set up`
        : `${agent.name} needs to sign in again`;
      const body = unprovisioned
        ? "Tap to choose a provider and sign in."
        : "vesta lost the provider credentials. Tap to re-authenticate.";
      try {
        const n = new Notification(title, {
          body,
          tag: `${agent.name}-${agent.status}`,
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
