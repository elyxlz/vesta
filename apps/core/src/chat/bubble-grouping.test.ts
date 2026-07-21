import { describe, expect, it } from "vitest"
import type { ChatMessage } from "./chat-stream-model"
import { BUBBLE_GROUP_TIME_GAP_MS, chatMessageSide, startsNewBubbleGroup } from "./bubble-grouping"

function user(ts?: string): ChatMessage {
  return { type: "user", text: "hi", ts }
}

function agent(ts?: string): ChatMessage {
  return { type: "chat", text: "hello", ts }
}

describe("chatMessageSide", () => {
  it("maps user to the user side and chat to the agent side", () => {
    expect(chatMessageSide(user())).toBe("user")
    expect(chatMessageSide(agent())).toBe("agent")
  })

  it("gives sideless rows no side", () => {
    expect(chatMessageSide({ type: "error", text: "boom" })).toBeNull()
    expect(
      chatMessageSide({ type: "rate_limited", text: "slow down", window: null, resets_at: null }),
    ).toBeNull()
  })
})

describe("startsNewBubbleGroup", () => {
  const base = "2026-07-15T10:00:00Z"
  const plus = (ms: number) => new Date(new Date(base).getTime() + ms).toISOString()

  it("keeps same-sender messages within the threshold tight", () => {
    expect(startsNewBubbleGroup(agent(base), agent(plus(BUBBLE_GROUP_TIME_GAP_MS - 1)))).toBe(false)
  })

  it("starts a new group at exactly the threshold", () => {
    expect(startsNewBubbleGroup(agent(base), agent(plus(BUBBLE_GROUP_TIME_GAP_MS)))).toBe(true)
  })

  it("starts a new group past the threshold", () => {
    expect(startsNewBubbleGroup(agent(base), agent(plus(BUBBLE_GROUP_TIME_GAP_MS + 1)))).toBe(true)
  })

  it("starts a new group on a sender change regardless of timing", () => {
    expect(startsNewBubbleGroup(user(base), agent(base))).toBe(true)
  })

  it("never starts a group with no previous side-carrying message", () => {
    expect(startsNewBubbleGroup(null, agent(base))).toBe(false)
  })

  it("falls back to tight when a timestamp is absent", () => {
    expect(startsNewBubbleGroup(user(), user())).toBe(false)
    expect(startsNewBubbleGroup(user(base), user())).toBe(false)
  })

  it("falls back to tight when a timestamp is unparseable", () => {
    expect(startsNewBubbleGroup(user(base), user("not-a-date"))).toBe(false)
    expect(startsNewBubbleGroup(user("not-a-date"), user(base))).toBe(false)
  })

  it("never starts a group off a sideless row", () => {
    expect(startsNewBubbleGroup({ type: "error", text: "boom" }, agent(base))).toBe(false)
  })
})
