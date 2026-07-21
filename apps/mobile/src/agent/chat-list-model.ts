import {
  chatMessageSide,
  startsNewBubbleGroup,
  type ChatMessage,
  type ChatMessageSide,
} from "@vesta/core";

export interface EventChatRow {
  kind: "event";
  key: string;
  event: ChatMessage;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
}

export interface TypingChatRow {
  kind: "typing";
  key: "typing-indicator";
  startsNewBubbleGroup: boolean;
}

export interface DateChatRow {
  kind: "date";
  key: string;
  timestamp: string;
}

export type ChatRow = EventChatRow | TypingChatRow | DateChatRow;

function calendarDay(timestamp: string | undefined): string | null {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function eventRows(events: ChatMessage[]): EventChatRow[] {
  const visible = events.filter(
    (event) =>
      event.type === "user" ||
      event.type === "chat" ||
      event.type === "error" ||
      event.type === "rate_limited",
  );
  const seen = new Map<string, number>();
  let previousSided: ChatMessage | null = null;
  const rows = visible.map((event) => {
    const base = `${event.ts ?? "live"}-${event.type}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const startsNew = startsNewBubbleGroup(previousSided, event);
    if (chatMessageSide(event)) previousSided = event;
    return {
      kind: "event" as const,
      key: count === 0 ? base : `${base}#${count}`,
      event,
      startsNewBubbleGroup: startsNew,
      endsBubbleGroup: false,
    };
  });

  let nextBubbleType: "user" | "chat" | null = null;
  let nextBubbleDay: string | null = null;
  let nextBubbleStartsNewGroup = false;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    if (!row) continue;
    const bubbleType =
      row.event.type === "user" || row.event.type === "chat"
        ? row.event.type
        : null;
    if (!bubbleType) continue;
    const bubbleDay = calendarDay(row.event.ts);
    row.endsBubbleGroup =
      nextBubbleType === null ||
      bubbleType !== nextBubbleType ||
      bubbleDay !== nextBubbleDay ||
      nextBubbleStartsNewGroup;
    nextBubbleType = bubbleType;
    nextBubbleDay = bubbleDay;
    nextBubbleStartsNewGroup = row.startsNewBubbleGroup;
  }
  return rows;
}

function addDateRows(rows: EventChatRow[]): ChatRow[] {
  const datedRows: ChatRow[] = [];
  let previousDay: string | null = null;

  for (const row of rows) {
    const day = calendarDay(row.event.ts);
    if (day && day !== previousDay && row.event.ts) {
      row.startsNewBubbleGroup = false;
      datedRows.push({
        kind: "date",
        key: `date-${day}`,
        timestamp: row.event.ts,
      });
    }
    datedRows.push(row);
    if (day) previousDay = day;
  }

  return datedRows;
}

export function createInvertedChatRows(
  events: ChatMessage[],
  isTyping: boolean,
): ChatRow[] {
  const rows = addDateRows(eventRows(events));
  if (isTyping) {
    let latestSide: ChatMessageSide | null = null;
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      const row = rows[index];
      if (!row || row.kind !== "event") continue;
      const side = chatMessageSide(row.event);
      if (side) {
        latestSide = side;
        if (row.event.type === "chat") row.endsBubbleGroup = false;
        break;
      }
    }
    rows.push({
      kind: "typing",
      key: "typing-indicator",
      startsNewBubbleGroup: latestSide === "user",
    });
  }

  return rows.reverse();
}
