import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import type { VestaEvent } from "@/lib/types";

export interface DecoratedRow {
  key: string;
  event: VestaEvent;
  gap: string;
  showDayStamp: boolean;
  dayLabel: string;
  isFirst: boolean;
}

export function rowKey(event: VestaEvent, idxFallback: number): string {
  return event.ts ? `${event.ts}-${event.type}` : `i-${idxFallback}`;
}

export function buildDecorated(chatMessages: VestaEvent[]): DecoratedRow[] {
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
    const isTool = msg.type === "tool_start";
    const prevIsTool = prev?.type === "tool_start";
    const gap = showDayStamp
      ? "mt-2"
      : i === 0
        ? ""
        : isTool && prevIsTool
          ? "mt-1"
          : isTool || prevIsTool
            ? "mt-2"
            : prev && prev.type === msg.type
              ? "mt-1.5"
              : "mt-5";
    const dayLabel =
      showDayStamp && msg.ts ? formatChatDayStampLabel(msg.ts) : "";
    const baseKey = rowKey(msg, i);
    const seen = seenKeys.get(baseKey) ?? 0;
    seenKeys.set(baseKey, seen + 1);
    return {
      key: seen === 0 ? baseKey : `${baseKey}#${seen}`,
      event: msg,
      gap,
      showDayStamp,
      dayLabel,
      isFirst: i === 0,
    };
  });
}
