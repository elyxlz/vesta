import { mergePending, type NotificationEvent } from "@vesta/core";

// The rows the notifications page lists: the loaded page, newest first, with every pending
// notification the page does not carry merged in above it. The pager renders the list inverted, so
// it reads it as it stands; the standalone sheet lays its rows out bottom-aligned instead and so
// reads the same list oldest first.
export function notificationRows(
  history: NotificationEvent[],
  pending: NotificationEvent[],
  standalone: boolean,
): NotificationEvent[] {
  const rows = mergePending(history, pending);
  return standalone ? [...rows].reverse() : rows;
}
