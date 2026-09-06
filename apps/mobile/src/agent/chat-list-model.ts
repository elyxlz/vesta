import {
  chatMessageSide,
  senderOf,
  startsNewBubbleGroup,
  type ChatMessage,
  type ChatMessageSide,
} from "@vesta/core";

export interface EventChatRow {
  kind: "event";
  key: string;
  event: ChatMessage;
  // Extra space above this bubble. A date header supplies its own separation, so the row under
  // one carries no gap even though it opens a group.
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
  // First bubble of its group. A room with several agents prints who spoke above this one.
  isGroupStart: boolean;
}

export interface TypingChatRow {
  kind: "typing";
  key: "typing-indicator";
  startsNewBubbleGroup: boolean;
}

export interface DateChatRow {
  kind: "date";
  key: string;
  timestamp: string | null;
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
    (event) => event.type === "user" || event.type === "chat",
  );
  const seen = new Map<string, number>();
  let previousSided: ChatMessage | null = null;
  const rows = visible.map((event) => {
    const base = `${event.ts ?? "live"}-${event.type}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const startsNew = startsNewBubbleGroup(previousSided, event);
    const sided = chatMessageSide(event) !== null;
    const opens = sided && (previousSided === null || startsNew);
    if (sided) previousSided = event;
    return {
      kind: "event" as const,
      key: count === 0 ? base : `${base}#${count}`,
      event,
      startsNewBubbleGroup: startsNew,
      endsBubbleGroup: false,
      isGroupStart: opens,
    };
  });

  // A group closes on the writer changing, not merely the side: two agents answering in one room
  // each get their own run of bubbles, and only the last of a run carries the tail.
  let nextSender: string | null = null;
  let nextBubbleDay: string | null = null;
  let nextBubbleStartsNewGroup = false;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    if (!row) continue;
    if (row.event.type !== "user" && row.event.type !== "chat") continue;
    const sender = senderOf(row.event);
    const bubbleDay = calendarDay(row.event.ts);
    row.endsBubbleGroup =
      nextSender === null ||
      sender !== nextSender ||
      bubbleDay !== nextBubbleDay ||
      nextBubbleStartsNewGroup;
    nextSender = sender;
    nextBubbleDay = bubbleDay;
    nextBubbleStartsNewGroup = row.startsNewBubbleGroup;
  }
  return rows;
}

function addDateRows(rows: EventChatRow[]): ChatRow[] {
  const datedRows: ChatRow[] = [];
  let previousBucket: string | null = null;

  for (const row of rows) {
    const day = calendarDay(row.event.ts);
    const bucket = day ?? "unknown";
    if (bucket !== previousBucket) {
      row.startsNewBubbleGroup = false;
      if (row.event.type === "user" || row.event.type === "chat")
        row.isGroupStart = true;
      datedRows.push({
        kind: "date",
        key: day ? `date-${day}` : `date-unknown-${row.key}`,
        timestamp: day && row.event.ts ? row.event.ts : null,
      });
    }
    datedRows.push(row);
    previousBucket = bucket;
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
