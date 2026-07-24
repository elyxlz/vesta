import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import type { Controller, Delta, Tree } from "@vesta/core";
import { useReplica } from "@vesta/core/react";
import { useGateway } from "@/providers/GatewayProvider";
import { ControllerContext } from "@/providers/ControllerProvider";
import { native } from "@/lib/native";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { useWindowFocus } from "@/hooks/use-window-focus";
import type { AgentRow } from "@/lib/types";
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

async function focusAndOpen(
  agentName: string,
  openAgent: (agentName: string) => void,
): Promise<void> {
  try {
    await native.focusWindow();
  } catch {
    /* ignore */
  }
  openAgent(agentName);
}

// The controller-driven half of the provider: it toasts the server's always-on `user_notification`
// deltas and lights the unseen badge from the replica's fleet-wide pending branch. Rendered only once
// the controller exists, so its hooks always have a live replica.
function ReplicaNotifications({
  controller,
  chattingAgentRef,
  notifyAssistant,
  notifyRateLimited,
  markUnseen,
}: {
  controller: Controller;
  chattingAgentRef: RefObject<string | null>;
  notifyAssistant: (agentName: string, text: string) => void;
  notifyRateLimited: (agentName: string, text: string) => void;
  markUnseen: () => void;
}) {
  // Toasts come from vestad's server-decided `user_notification` deltas (each carries a display triple:
  // kind/title/body), independent of any subscription. A rate limit toasts even while focused; a
  // chat lights the unseen badge and toasts, deferring the actively-chatted agent to
  // AgentSocketProvider (which fires after the typing delay so it lines up with the visible bubble).
  useEffect(() => {
    return controller.subscribeDeltas((delta: Delta) => {
      if (delta.type !== "user_notification") return;
      const { agent, kind, body } = delta;
      if (kind === "rate_limited") {
        notifyRateLimited(agent, body);
        return;
      }
      markUnseen();
      if (chattingAgentRef.current === agent) return;
      notifyAssistant(agent, body);
    });
  }, [
    controller,
    notifyAssistant,
    notifyRateLimited,
    chattingAgentRef,
    markUnseen,
  ]);

  // The fleet-wide pending count is the replica's always-on truth for unprocessed notifications.
  // A rising count while hidden means a new one arrived somewhere: light the unseen badge.
  const pendingCount = useReplica(controller.replica, (tree: Tree | null) =>
    tree
      ? Object.values(tree.agents).reduce(
          (sum, node) => sum + node.notifications.pending.length,
          0,
        )
      : 0,
  );
  const prevPendingRef = useRef(pendingCount);
  useEffect(() => {
    const grew = pendingCount > prevPendingRef.current;
    prevPendingRef.current = pendingCount;
    if (grew) markUnseen();
  }, [pendingCount, markUnseen]);

  return null;
}

export function NotificationProvider({
  children,
  onOpenAgent,
}: {
  children: ReactNode;
  onOpenAgent: (agentName: string) => void;
}) {
  const { agents } = useGateway();
  const controller = useContext(ControllerContext);
  const focused = useWindowFocus();
  const focusedRef = useRef(focused);
  useEffect(() => {
    focusedRef.current = focused;
  }, [focused]);

  const permissionRef = useRef<boolean>(false);
  const chattingAgentRef = useRef<string | null>(null);
  const prevStatusRef = useRef<Map<string, AgentRow["status"]>>(new Map());

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

  // Light the unseen badge only while the window is hidden; a focused window is already seen.
  const markUnseen = useCallback(() => {
    if (!document.hidden) return;
    setAppBadge(true);
    setFaviconUnseen(true);
  }, []);

  const notifyAssistant = useCallback(
    (agentName: string, text: string) => {
      if (focusedRef.current) return;
      if (!permissionRef.current) return;
      const body = text.trim();
      if (!body) return;
      try {
        const n = new Notification(agentName, {
          body: truncate(body),
          tag: agentName,
        });
        const autoClose = setTimeout(
          () => n.close(),
          NOTIFICATION_AUTO_CLOSE_MS,
        );
        n.onclick = () => {
          clearTimeout(autoClose);
          void focusAndOpen(agentName, onOpenAgent);
          n.close();
        };
        n.onclose = () => clearTimeout(autoClose);
      } catch {
        /* ignore */
      }
    },
    [onOpenAgent],
  );

  // Unlike chat previews, a hit rate limit fires even while the app is focused: the chat
  // surface shows nothing for a throttled turn, so this is the user's only signal.
  const notifyRateLimited = useCallback(
    (agentName: string, text: string) => {
      if (!permissionRef.current) return;
      try {
        const n = new Notification(`${agentName} hit a Claude rate limit`, {
          body: text,
          tag: `${agentName}-rate-limited`,
        });
        n.onclick = () => {
          void focusAndOpen(agentName, onOpenAgent);
          n.close();
        };
      } catch {
        /* ignore */
      }
    },
    [onOpenAgent],
  );

  const setChattingAgent = useCallback((agentName: string | null) => {
    chattingAgentRef.current = agentName;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void ensurePermission().then((granted) => {
      if (!cancelled) permissionRef.current = granted;
    });
    return () => {
      cancelled = true;
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
          void focusAndOpen(agent.name, onOpenAgent);
          n.close();
        };
      } catch {
        /* ignore */
      }
    }
  }, [agents, onOpenAgent]);

  const value = useMemo(
    () => ({ notifyAssistant, setChattingAgent }),
    [notifyAssistant, setChattingAgent],
  );

  return (
    <NotificationContext.Provider value={value}>
      {controller ? (
        <ReplicaNotifications
          controller={controller}
          chattingAgentRef={chattingAgentRef}
          notifyAssistant={notifyAssistant}
          notifyRateLimited={notifyRateLimited}
          markUnseen={markUnseen}
        />
      ) : null}
      {children}
    </NotificationContext.Provider>
  );
}
