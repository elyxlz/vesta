import { useMemo, useRef } from "react";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import type { VestaEvent } from "@/lib/types";

export const START_INDEX = 1_000_000;

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
  // timestamp and type. Suffix repeats so keys stay unique for React/Virtuoso
  // and so the head-diff in computeFirstIndexShift can rely on indexOf.
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

// Virtuoso keeps scroll position stable across prepends only if `firstItemIndex`
// is decremented by the number of items added to the FRONT of the list (and
// incremented when items drop off the front, which happens at the MAX_MESSAGES
// cap). A pure tail append/change needs no adjustment. We derive the head delta
// by diffing the previous and next row-key arrays.
export function computeFirstIndexShift(
  prevKeys: string[],
  nextKeys: string[],
  prevFirstIndex: number,
): number {
  if (prevKeys.length === 0 || nextKeys.length === 0) return prevFirstIndex;

  const prependCount = nextKeys.indexOf(prevKeys[0]);
  if (prependCount > 0) return prevFirstIndex - prependCount;
  if (prependCount === 0) return prevFirstIndex;

  // Old head is gone: either the front was dropped at the cap, or the list was
  // reset (agent switch / reconnect / filter toggle).
  const dropCount = prevKeys.indexOf(nextKeys[0]);
  if (dropCount > 0) return prevFirstIndex + dropCount;
  return START_INDEX;
}

export function useStableFirstItemIndex(rows: DecoratedRow[]): number {
  const prevKeysRef = useRef<string[]>([]);
  const firstIndexRef = useRef(START_INDEX);

  return useMemo(() => {
    const nextKeys = rows.map((r) => r.key);
    if (nextKeys.length === 0) {
      prevKeysRef.current = [];
      firstIndexRef.current = START_INDEX;
      return START_INDEX;
    }
    if (prevKeysRef.current.length === 0) {
      prevKeysRef.current = nextKeys;
      return firstIndexRef.current;
    }
    const next = computeFirstIndexShift(
      prevKeysRef.current,
      nextKeys,
      firstIndexRef.current,
    );
    firstIndexRef.current = next;
    prevKeysRef.current = nextKeys;
    return next;
  }, [rows]);
}
