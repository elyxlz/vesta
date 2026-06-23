import { useMemo, useRef } from "react";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import type { VestaEvent } from "@/lib/types";

export const START_INDEX = 1_000_000;

export interface DecoratedRow {
  key: string;
  event: VestaEvent;
  tools: VestaEvent[];
  gap: string;
  showDayStamp: boolean;
  dayLabel: string;
  isFirst: boolean;
}

export function rowKey(event: VestaEvent, idxFallback: number): string {
  return event.ts ? `${event.ts}-${event.type}` : `i-${idxFallback}`;
}

export function buildDecorated(messages: VestaEvent[]): DecoratedRow[] {
  // One row per conversation message (user/chat); tool calls are grouped onto the row of the
  // message they follow. The row set is therefore independent of the show-tools toggle, so
  // toggling changes only row heights — never the virtual list's item count — and scroll
  // position holds. (A mid-list insert/remove makes Virtuoso lose its firstItemIndex anchor.)
  const rows: DecoratedRow[] = [];
  let lastDayKey: string | null = null;
  // rowKey (`${ts}-${type}`) is not guaranteed unique — two messages can share a timestamp
  // and type. Suffix repeats so keys stay unique for React/Virtuoso and the head-diff in
  // computeFirstIndexShift can rely on indexOf.
  const seenKeys = new Map<string, number>();
  messages.forEach((msg, i) => {
    if (msg.type === "tool_start") {
      // Attach to the preceding conversation row. A leading tool with no row to attach to is
      // dropped — the windowed history always opens on a conversation message.
      if (rows.length > 0) rows[rows.length - 1].tools.push(msg);
      return;
    }
    const prev = rows.length > 0 ? rows[rows.length - 1].event : undefined;
    const dayKey = calendarDayKey(msg.ts);
    const showDayStamp = Boolean(
      dayKey && (lastDayKey === null || dayKey !== lastDayKey),
    );
    if (dayKey) lastDayKey = dayKey;
    const isFirst = rows.length === 0;
    const gap = showDayStamp
      ? "mt-2"
      : isFirst
        ? ""
        : prev && prev.type === msg.type
          ? "mt-1.5"
          : "mt-5";
    const dayLabel =
      showDayStamp && msg.ts ? formatChatDayStampLabel(msg.ts) : "";
    const baseKey = rowKey(msg, i);
    const seen = seenKeys.get(baseKey) ?? 0;
    seenKeys.set(baseKey, seen + 1);
    rows.push({
      key: seen === 0 ? baseKey : `${baseKey}#${seen}`,
      event: msg,
      tools: [],
      gap,
      showDayStamp,
      dayLabel,
      isFirst,
    });
  });
  return rows;
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
