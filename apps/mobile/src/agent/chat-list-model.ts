import type { VestaEvent } from "../api/types";

export interface EventChatRow {
  kind: "event";
  key: string;
  event: VestaEvent;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
}

export interface TypingChatRow {
  kind: "typing";
  key: "typing-indicator";
  startsNewBubbleGroup: boolean;
}

export type ChatRow = EventChatRow | TypingChatRow;

function eventRows(
  events: VestaEvent[],
  showToolCalls: boolean,
): EventChatRow[] {
  const visible = events.filter(
    (event) =>
      event.type === "user" ||
      event.type === "chat" ||
      event.type === "error" ||
      event.type === "rate_limited" ||
      (showToolCalls &&
        event.type === "tool_start" &&
        !(event.tool === "Bash" && event.input.includes("app-chat"))),
  );
  const seen = new Map<string, number>();
  let previousBubbleType: "user" | "chat" | null = null;
  const rows = visible.map((event) => {
    const base = `${event.ts ?? "live"}-${event.type}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const bubbleType =
      event.type === "user" || event.type === "chat" ? event.type : null;
    const startsNewBubbleGroup = Boolean(
      bubbleType && previousBubbleType && bubbleType !== previousBubbleType,
    );
    if (bubbleType) previousBubbleType = bubbleType;
    return {
      kind: "event" as const,
      key: count === 0 ? base : `${base}#${count}`,
      event,
      startsNewBubbleGroup,
      endsBubbleGroup: false,
    };
  });

  let nextBubbleType: "user" | "chat" | null = null;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    if (!row) continue;
    const bubbleType =
      row.event.type === "user" || row.event.type === "chat"
        ? row.event.type
        : null;
    if (!bubbleType) continue;
    row.endsBubbleGroup =
      nextBubbleType === null || bubbleType !== nextBubbleType;
    nextBubbleType = bubbleType;
  }
  return rows;
}

export function createInvertedChatRows(
  events: VestaEvent[],
  showToolCalls: boolean,
  isTyping: boolean,
): ChatRow[] {
  const rows: ChatRow[] = eventRows(events, showToolCalls);
  if (isTyping) {
    let latestBubbleType: "user" | "chat" | null = null;
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      const row = rows[index];
      if (!row || row.kind !== "event") continue;
      if (row.event.type === "user" || row.event.type === "chat") {
        latestBubbleType = row.event.type;
        if (latestBubbleType === "chat") row.endsBubbleGroup = false;
        break;
      }
    }
    rows.push({
      kind: "typing",
      key: "typing-indicator",
      startsNewBubbleGroup: latestBubbleType === "user",
    });
  }

  return rows.reverse();
}
