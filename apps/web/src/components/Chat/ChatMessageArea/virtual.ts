import { startsNewBubbleGroup } from "@vesta/core";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import type { ChatMessage } from "@/lib/types";

export interface DecoratedRow {
  key: string;
  event: ChatMessage;
  gap: string;
  showDayStamp: boolean;
  dayLabel: string;
  isFirst: boolean;
}

export function rowKey(event: ChatMessage, idxFallback: number): string {
  return event.ts ? `${event.ts}-${event.type}` : `i-${String(idxFallback)}`;
}

function rowGap(
  msg: ChatMessage,
  prev: ChatMessage | undefined,
  showDayStamp: boolean,
  index: number,
): string {
  if (showDayStamp) return "mt-2";
  if (index === 0) return "";
  if (prev?.type !== msg.type) return "mt-5";
  // Same sender: tight, unless a >= 5-minute pause splits them into a fresh bubble group.
  return startsNewBubbleGroup(prev, msg) ? "mt-5" : "mt-1.5";
}

export function buildDecorated(chatMessages: ChatMessage[]): DecoratedRow[] {
  let lastDayKey: string | null = null;
  // rowKey (`${ts}-${type}`) is not guaranteed unique — two events can share a
  // timestamp and type. Suffix repeats so keys stay unique, which the virtualizer's
  // getItemKey needs to track (and re-anchor) a row across data changes.
  const seenKeys = new Map<string, number>();
  return chatMessages.map((msg, i) => {
    const prev = chatMessages[i - 1];
    const dayKey = calendarDayKey(msg.ts);
    const showDayStamp = Boolean(
      dayKey && (lastDayKey === null || dayKey !== lastDayKey),
    );
    if (dayKey) lastDayKey = dayKey;
    const gap = rowGap(msg, prev, showDayStamp, i);
    const dayLabel =
      showDayStamp && msg.ts ? formatChatDayStampLabel(msg.ts) : "";
    const baseKey = rowKey(msg, i);
    const seen = seenKeys.get(baseKey) ?? 0;
    seenKeys.set(baseKey, seen + 1);
    return {
      key: seen === 0 ? baseKey : `${baseKey}#${String(seen)}`,
      event: msg,
      gap,
      showDayStamp,
      dayLabel,
      isFirst: i === 0,
    };
  });
}
