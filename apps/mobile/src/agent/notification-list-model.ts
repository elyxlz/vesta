import type { ChatMessage } from "@/chat/chat-stream-model";
import type { NotificationView } from "@/agent/notification-content";

function notificationKey(event: NotificationView): string {
  return (
    event.notif_id ??
    event.ts ??
    `${event.source}\u0000${event.sender ?? ""}\u0000${event.summary}`
  );
}

export function mergeLiveNotifications(
  history: readonly NotificationView[],
  liveEvents: readonly ChatMessage[],
): NotificationView[] {
  const seen = new Set(history.map(notificationKey));
  const arrivals: NotificationView[] = [];

  for (const event of liveEvents) {
    if (event.type !== "notification") continue;
    const key = notificationKey(event);
    if (seen.has(key)) continue;
    seen.add(key);
    arrivals.push(event);
  }

  return [...arrivals.reverse(), ...history];
}

export function getPendingNotificationIds(
  pendingSeed: string[],
  liveEvents: readonly ChatMessage[],
): Set<string> {
  const pending = new Set(pendingSeed);

  for (const event of liveEvents) {
    if (event.type === "notification" && event.notif_id) {
      pending.add(event.notif_id);
    } else if (event.type === "notification_cleared") {
      pending.delete(event.notif_id);
    }
  }

  return pending;
}
