import type { ChatMessage } from "./chat-stream-model"

// Two same-sender messages closer together than this render as one tight bubble group; a longer
// same-sender pause (or a sender change) starts a fresh group. Owned here so web and mobile share
// one grouping decision and cannot drift.
export const BUBBLE_GROUP_TIME_GAP_MS = 5 * 60 * 1000

export type ChatMessageSide = "user" | "agent"

// The conversational side a chat row belongs to. Only user/chat rows carry a side; error and
// rate_limited rows have none, so they never open or close a bubble group.
export function chatMessageSide(message: ChatMessage): ChatMessageSide | null {
  if (message.type === "user") return "user"
  if (message.type === "chat") return "agent"
  return null
}

function timestampMillis(ts: string | undefined): number | null {
  if (!ts) return null
  const value = new Date(ts).getTime()
  return Number.isNaN(value) ? null : value
}

// Does `curr` begin a new visual bubble group after the previous rendered side-carrying message
// `prev`? A sender change or a >= BUBBLE_GROUP_TIME_GAP_MS same-sender gap starts a new group;
// same-sender rows within the threshold group tight. An absent or unparseable timestamp falls back
// to tight (never throws), and a sideless prev/curr (error, rate_limited) never starts a group.
export function startsNewBubbleGroup(prev: ChatMessage | null, curr: ChatMessage): boolean {
  const currSide = chatMessageSide(curr)
  const prevSide = prev ? chatMessageSide(prev) : null
  if (!currSide || !prevSide) return false
  if (currSide !== prevSide) return true
  const prevTs = prev ? timestampMillis(prev.ts) : null
  const currTs = timestampMillis(curr.ts)
  if (prevTs === null || currTs === null) return false
  return currTs - prevTs >= BUBBLE_GROUP_TIME_GAP_MS
}
