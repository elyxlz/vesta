import { notificationRowKey } from "../notification-content/notification-content";
import type { NotificationEvent } from "../protocol/events";

// A pending notification the history page does not carry gets a row of its own, above the page: the
// pending list grows at its end as notifications land, so reversing it puts the newest first. A
// pending entry vestad only knows by id carries no timestamp, so a row key alone would not match
// the stored arrival; the notif_id it always carries is what says the page already shows it.
export function mergePending(
  history: NotificationEvent[],
  pending: NotificationEvent[],
): NotificationEvent[] {
  const keys = new Set(history.map(notificationRowKey));
  const ids = new Set(
    history.flatMap((event) => (event.notif_id ? [event.notif_id] : [])),
  );
  const missing = pending.filter(
    (event) =>
      !keys.has(notificationRowKey(event)) &&
      !(event.notif_id != null && ids.has(event.notif_id)),
  );
  return missing.length === 0
    ? history
    : [...[...missing].reverse(), ...history];
}

// Whether two reads of the pending set name the same arrivals in the same order. The replica hands
// out a fresh array on every delta, so this is what keeps a view that reads the set from
// re-rendering when nothing about the set changed.
export function samePendingNotifications(
  a: NotificationEvent[],
  b: NotificationEvent[],
): boolean {
  return (
    a.length === b.length &&
    a.every((event, index) => {
      const other = b[index];
      return (
        other !== undefined &&
        notificationRowKey(event) === notificationRowKey(other)
      );
    })
  );
}
