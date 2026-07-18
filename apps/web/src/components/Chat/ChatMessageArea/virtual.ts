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
  return event.ts ? `${event.ts}-${event.type}` : `i-${String(idxFallback)}`;
}

// A same-sender run resumed after this long reads as a new beat, so it gets the
// wider alternating-style gap instead of the tight same-sender one.
const TIME_GAP_THRESHOLD_MS = 5 * 60 * 1000;

function elapsedAtLeastThreshold(
  msg: VestaEvent,
  prev: VestaEvent | undefined,
): boolean {
  if (!msg.ts || !prev?.ts) return false;
  const now = Date.parse(msg.ts);
  const before = Date.parse(prev.ts);
  if (Number.isNaN(now) || Number.isNaN(before)) return false;
  return now - before >= TIME_GAP_THRESHOLD_MS;
}

function rowGap(
  msg: VestaEvent,
  prev: VestaEvent | undefined,
  showDayStamp: boolean,
  index: number,
): string {
  if (showDayStamp) return "mt-2";
  if (index === 0) return "";
  const isTool = msg.type === "tool_start";
  const prevIsTool = prev?.type === "tool_start";
  if (isTool && prevIsTool) return "mt-1";
  if (isTool || prevIsTool) return "mt-2";
  if (prev?.type !== msg.type) return "mt-5";
  return elapsedAtLeastThreshold(msg, prev) ? "mt-5" : "mt-1.5";
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
