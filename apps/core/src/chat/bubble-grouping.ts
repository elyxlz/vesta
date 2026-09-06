import type { ChatMessage } from "./chat-stream-model";

// Two same-sender messages closer together than this render as one tight bubble group; a longer
// same-sender pause (or a sender change) starts a fresh group. Owned here so web and mobile share
// one grouping decision and cannot drift.
export const BUBBLE_GROUP_TIME_GAP_MS = 5 * 60 * 1000;

export type ChatMessageSide = "user" | "agent";

// The conversational side a chat row belongs to. Only user and chat rows carry a side; any other
// row has none, so it never opens or closes a bubble group.
export function chatMessageSide(message: ChatMessage): ChatMessageSide | null {
  if (message.type === "user") return "user";
  if (message.type === "chat") return "agent";
  return null;
}

// Who wrote a row. A room stamps the member's name on every message; a row from a chat that names
// nobody answers its side, so a one-agent conversation groups exactly as it always did. A sideless
// row answers the agent side and never reaches a grouping decision.
export function senderOf(message: ChatMessage): string {
  const named =
    message.type === "user" || message.type === "chat"
      ? message.sender
      : undefined;
  return named ?? (message.type === "user" ? "user" : "agent");
}

function timestampMillis(ts: string | undefined): number | null {
  if (!ts) return null;
  const value = new Date(ts).getTime();
  return Number.isNaN(value) ? null : value;
}

// Does `curr` begin a new visual bubble group after the previous rendered side-carrying message
// `prev`? A change of side, a change of sender (a second agent speaking in a room), or a
// >= BUBBLE_GROUP_TIME_GAP_MS same-sender gap starts a new group; same-sender rows within the
// threshold group tight. An absent or unparseable timestamp falls back to tight (never throws),
// and a sideless prev/curr never starts a group.
export function startsNewBubbleGroup(
  prev: ChatMessage | null,
  curr: ChatMessage,
): boolean {
  if (prev === null) return false;
  const currSide = chatMessageSide(curr);
  const prevSide = chatMessageSide(prev);
  if (!currSide || !prevSide) return false;
  if (currSide !== prevSide) return true;
  if (senderOf(prev) !== senderOf(curr)) return true;
  const prevTs = timestampMillis(prev.ts);
  const currTs = timestampMillis(curr.ts);
  if (prevTs === null || currTs === null) return false;
  return currTs - prevTs >= BUBBLE_GROUP_TIME_GAP_MS;
}
