import type { FeedSections, NotificationFeed } from "@vesta/core";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";

export const POPOVER_ROWS = 4;

// Whether the archive holds more than the popover shows, which is what
// earns the "see all" footer. Read from the cached rows alone, never the
// refetch every open starts, so the footer is there the instant the popover
// is.
export function archiveExtendsBeyond(
  feed: NotificationFeed,
  sections: FeedSections,
): boolean {
  if (feed.entries.length === 0) return false;
  if (sections) return true;
  return feed.entries.length > POPOVER_ROWS || feed.older !== "exhausted";
}

export function dayKey(atSeconds: number): string | null {
  return calendarDayKey(new Date(atSeconds * 1000).toISOString());
}

// Today's group carries no label (the freshest rows just start); the labels
// begin at yesterday, then fall to the chat's day-stamp rule so the two
// history surfaces date rows identically.
export function formatDayLabel(atSeconds: number): string {
  const date = new Date(atSeconds * 1000);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "";
  if (date.toDateString() === yesterday.toDateString()) return "yesterday";
  return formatChatDayStampLabel(date.toISOString());
}
