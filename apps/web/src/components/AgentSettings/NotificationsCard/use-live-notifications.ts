import { useContext, useMemo } from "react";
import { AgentSocketContext } from "@/providers/AgentSocketProvider/context";
import type { NotificationEvent } from "@/api/agents";

// Bridges the agent socket's live event stream into the notifications view. Reads the context
// tolerantly (no throw) so the card still renders REST-only when there's no AgentSocketProvider
// (e.g. in tests). Surfaces live notification arrivals and the ids cleared since connect.
export function useLiveNotifications(): {
  arrivals: NotificationEvent[];
  cleared: string[];
  connected: boolean;
} {
  const socket = useContext(AgentSocketContext);
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

  return { arrivals, cleared, connected: socket?.connected ?? false };
}
