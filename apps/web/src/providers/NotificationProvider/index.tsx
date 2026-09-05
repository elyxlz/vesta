import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import {
  directRoomId,
  roomKind,
  selectRooms,
  type Delta,
  type Tree,
} from "@vesta/core";
import { useReplica } from "@vesta/core/react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { native } from "@/lib/native";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { NotificationContext } from "./context";

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

async function focusAndOpen(open: () => void): Promise<void> {
  try {
    await native.focusWindow();
  } catch {
    /* ignore */
  }
  open();
}

// The fleet-wide pending count is the replica's always-on truth for unprocessed notifications.
function selectPendingCount(tree: Tree | null): number {
  return tree
    ? Object.values(tree.agents).reduce(
        (sum, node) => sum + node.notifications.pending.length,
        0,
      )
    : 0;
}

export function NotificationProvider({
  children,
  onOpenAgent,
  onOpenRoom,
}: {
  children: ReactNode;
  onOpenAgent: (agentName: string) => void;
  // Where a room notification lands: a direct room opens its agent's chat, anything else the
  // room route. The direct agent is resolved here, off the replica, at click time.
  onOpenRoom: (roomId: string, directAgent: string | null) => void;
}) {
  // Null before the controller exists; every hook below answers the null with its idle value, so
  // the provider's hook order never depends on the connection. Focus, the viewed agent, and the
  // fleet-wide focus flag are all read from the controller at call time: one owner, no mirror.
  const controller = useOptionalController();
  const permissionRef = useRef<boolean>(false);

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

  // Muted while this window or any client anywhere is focused (vestad broadcasts the global flag).
  const anyoneFocused = useCallback(
    () =>
      (controller?.getFocused() ?? false) ||
      (controller?.getAnyFocused() ?? false),
    [controller],
  );

  // The room a notification belongs to, resolved to its direct agent when it has one. Read off
  // the replica at call time rather than subscribed, so the roster churning never re-renders here.
  const directAgentOf = useCallback(
    (roomId: string): string | null => {
      const room = selectRooms(controller?.replica.getState() ?? null).find(
        (candidate) => candidate.id === roomId,
      );
      if (!room || roomKind(room) !== "direct") return null;
      return room.agents[0] ?? null;
    },
    [controller],
  );

  const notifyAssistant = useCallback(
    (sender: string, text: string, room: string) => {
      if (anyoneFocused()) return;
      if (!permissionRef.current) return;
      const body = text.trim();
      if (!body) return;
      try {
        const n = new Notification(sender, {
          body: truncate(body),
          tag: room,
        });
        const autoClose = setTimeout(
          () => n.close(),
          NOTIFICATION_AUTO_CLOSE_MS,
        );
        n.onclick = () => {
          clearTimeout(autoClose);
          void focusAndOpen(() => {
            onOpenRoom(room, directAgentOf(room));
          });
          n.close();
        };
        n.onclose = () => clearTimeout(autoClose);
      } catch {
        /* ignore */
      }
    },
    [anyoneFocused, directAgentOf, onOpenRoom],
  );

  // Unlike chat previews, a needs-user alert (set up, sign in, rate limited) fires even while
  // the app is focused: the chat surface shows nothing for it, so this is the user's only
  // signal. The server decides the title; tapping it opens the agent, where the fix lives.
  const notifyNeedsUser = useCallback(
    (agentName: string, title: string, text: string) => {
      if (!permissionRef.current) return;
      try {
        const n = new Notification(title, {
          body: truncate(text),
          tag: `${agentName}-needs-user`,
        });
        n.onclick = () => {
          void focusAndOpen(() => {
            onOpenAgent(agentName);
          });
          n.close();
        };
      } catch {
        /* ignore */
      }
    },
    [onOpenAgent],
  );

  // The gateway announces an update only to clients that were away for it, so this raises with the
  // same focus mute as a chat preview and opens nothing: there is no agent behind it.
  const notifyGateway = useCallback(
    (title: string, text: string) => {
      if (anyoneFocused()) return;
      if (!permissionRef.current) return;
      try {
        new Notification(title, { body: truncate(text), tag: "gateway" });
      } catch {
        /* ignore */
      }
    },
    [anyoneFocused],
  );

  useEffect(() => {
    let cancelled = false;
    void ensurePermission().then((granted) => {
      if (!cancelled) permissionRef.current = granted;
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Toasts come from vestad's server-decided `user_notification` deltas (each carries a display
  // triple: kind/title/body), independent of any subscription. A needs-user alert (set up, sign
  // in, rate limited) toasts even while focused, since the chat surface shows nothing for it; a
  // chat lights the unseen badge and toasts, deferring the room the user is looking at to
  // RoomSocketProvider (which fires after the typing delay so it lines up with the visible bubble).
  useEffect(() => {
    if (!controller) return;
    return controller.subscribeDeltas((delta: Delta) => {
      if (delta.type !== "user_notification") return;
      const { agent, kind, title, body } = delta;
      // LEGACY(remove-when: no supported gateway emits kind=rate_limited; it
      // was renamed needs_user alongside the durable notification log):
      if (kind === "needs_user" || kind === "rate_limited") {
        notifyNeedsUser(agent, title, body);
        return;
      }
      // The gateway's own announcement, sent only to clients that missed the update: it names no
      // agent, so it carries its own title and lights no unseen badge.
      if (kind === "gateway_updated") {
        notifyGateway(title, body);
        return;
      }
      markUnseen();
      // A reply carries the room it landed in; a notice vestad minted about the agent itself (a
      // finished task) carries none, so it falls back to that agent's own conversation.
      const room = delta.room ?? directRoomId(agent);
      if (room === controller.getViewing()) return;
      notifyAssistant(title, body, room);
    });
  }, [controller, notifyAssistant, notifyNeedsUser, notifyGateway, markUnseen]);

  // A rising pending count while hidden means a new one arrived somewhere: light the unseen badge.
  const pendingCount = useReplica(
    controller?.replica ?? null,
    selectPendingCount,
  );
  const prevPendingRef = useRef(pendingCount);
  useEffect(() => {
    const grew = pendingCount > prevPendingRef.current;
    prevPendingRef.current = pendingCount;
    if (grew) markUnseen();
  }, [pendingCount, markUnseen]);

  const value = useMemo(() => ({ notifyAssistant }), [notifyAssistant]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}
