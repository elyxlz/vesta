import { useCallback, useContext, useMemo } from "react";
import type { NotificationEvent, Tree } from "@vesta/core";
import { useReplica } from "@vesta/core/react";
import { useController } from "@/providers/ControllerProvider/context";
import { RoomSocketContext } from "@/providers/RoomSocketProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

// Bridges the agent's live room into the notifications view. Reads the socket context tolerantly
// (no throw) so the card still renders REST-only when there is no RoomSocketProvider. The pending
// seed is an agent fact, so it comes off the replica rather than the conversation.
export function useLiveNotifications(): {
  pendingSeed: string[];
  arrivals: NotificationEvent[];
  cleared: string[];
  connected: boolean;
} {
  const { name } = useSelectedAgent();
  const controller = useController();
  const socket = useContext(RoomSocketContext);
  const messages = socket?.messages;

  const arrivals = useMemo(
    () =>
      (messages ?? []).filter(
        (event): event is NotificationEvent => event.type === "notification",
      ),
    [messages],
  );

  const cleared = useMemo(
    () =>
      (messages ?? []).flatMap((event) =>
        event.type === "notification_cleared" ? [event.notif_id] : [],
      ),
    [messages],
  );

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      (tree?.agents[name]?.notifications.pending ?? []).flatMap((notif) =>
        notif.notif_id ? [notif.notif_id] : [],
      ),
    [name],
  );
  const pendingSeed = useReplica(controller.replica, pendingSelector, idsEqual);

  return {
    pendingSeed,
    arrivals,
    cleared,
    connected: socket?.connected ?? false,
  };
}
