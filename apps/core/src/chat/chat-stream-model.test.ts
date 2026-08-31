import { describe, expect, it } from "vitest"
import type { VestaEvent } from "../protocol/events"
import {
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  retryableSends,
  seedTail,
  trimTail,
  type ChatMessage,
  type ChatState,
} from "./chat-stream-model"

function chat(id: number, text: string): VestaEvent {
  return { type: "chat", text, id }
}

// The append echo of a send: a wire `user` event carrying the client `intent_id`. Core's event type
// does not model that client-only field, so assert past it as the runtime frame does.
function userEcho(id: number, text: string, intentId: string): ChatMessage {
  return { type: "user", text, id, intent_id: intentId }
}

function users(state: ChatState) {
  return state.messages.filter((message) => message.type === "user")
}

describe("chat-stream-model", () => {
  it("registers the intent and pushes an optimistic sending bubble on beginSend", () => {
    const state = beginSend(initialChatState(), "hi", "typed", "i-1")
    expect(state.pendingIntents.has("i-1")).toBe(true)
    expect(users(state)).toHaveLength(1)
    expect(users(state)[0]).toMatchObject({ text: "hi", send_state: "sending" })
  })

  it("confirms the optimistic bubble by intent_id without duplicating it (dedup by id, not text)", () => {
    let state = beginSend(initialChatState(), "hi", "typed", "i-1")
    ;({ state } = foldLiveEvent(state, userEcho(5, "hi", "i-1")))
    expect(users(state)).toHaveLength(1)
    expect(users(state)[0]?.send_state).toBeUndefined()
    expect(users(state)[0]?.id).toBe(5)
    expect(state.pendingIntents.has("i-1")).toBe(false)
    expect(state.shownIds.has(5)).toBe(true)
  })

  it("flags a live chat as paced and withholds it from the tail", () => {
    const { state, paced } = foldLiveEvent(initialChatState(), chat(7, "pong"))
    expect(paced).toBe(true)
    expect(state.messages).toHaveLength(0)
    expect(state.shownIds.has(7)).toBe(true)
  })

  it("appends a paced chat on commit", () => {
    const { state } = foldLiveEvent(initialChatState(), chat(7, "pong"))
    const committed = commitPacedChat(state, chat(7, "pong"))
    expect(committed.messages.map((m) => m.type)).toEqual(["chat"])
  })

  it("does not re-add a paced chat whose id a reseed already merged before the delay elapsed", () => {
    // A live chat is folded (paced, queued) but not yet committed; then a reconnect tail refetch
    // merges the same id into the tail. The later paced commit must not duplicate that row.
    const { state: folded, paced } = foldLiveEvent(initialChatState(), chat(7, "pong"))
    expect(paced).toBe(true)
    const reseeded = seedTail(folded, { events: [chat(7, "pong")], cursor: null })
    expect(reseeded.messages).toHaveLength(1)
    const committed = commitPacedChat(reseeded, chat(7, "pong"))
    expect(committed.messages.map((m) => m.type)).toEqual(["chat"])
  })

  it("drops a persisted row whose id was already shown", () => {
    const seeded = seedTail(initialChatState(), { events: [chat(2, "b")], cursor: null })
    const { state, paced } = foldLiveEvent(seeded, chat(2, "b"))
    expect(paced).toBe(false)
    expect(state.messages).toHaveLength(1)
  })

  it("appends a non-chat live event immediately", () => {
    const error: VestaEvent = { type: "error", text: "boom", id: 9 }
    const { state, paced } = foldLiveEvent(initialChatState(), error)
    expect(paced).toBe(false)
    expect(state.messages.map((m) => m.type)).toEqual(["error"])
  })

  it("filters tool events out of the live fold so no tool row ever enters messages", () => {
    const toolStart: VestaEvent = { type: "tool_start", tool: "Bash", input: "ls", id: 11 }
    const toolEnd: VestaEvent = { type: "tool_end", tool: "Bash", id: 12 }
    let { state, paced } = foldLiveEvent(initialChatState(), toolStart)
    expect(paced).toBe(false)
    expect(state.messages).toHaveLength(0)
    expect(state.shownIds.has(11)).toBe(false)
    ;({ state, paced } = foldLiveEvent(state, toolEnd))
    expect(paced).toBe(false)
    expect(state.messages).toHaveLength(0)
  })

  it("seedTail keeps an in-flight optimistic bubble and a raced live row, merging not replacing", () => {
    let state = beginSend(initialChatState(), "hi", "typed", "i-1")
    const raced = foldLiveEvent(state, chat(99, "raced"))
    state = commitPacedChat(raced.state, chat(99, "raced"))
    state = seedTail(state, { events: [chat(1, "seed")], cursor: null })

    const texts = state.messages.map((m) =>
      m.type === "chat" ? m.text : m.type === "user" ? "hi" : "",
    )
    expect(texts).toEqual(["seed", "hi", "raced"])
    expect(texts.filter((t) => t === "raced")).toHaveLength(1)
    expect(users(state)[0]).toMatchObject({ send_state: "sending" })
  })

  it("reconciles a pending optimistic bubble against a reseed page that already carries its echo", () => {
    let state = beginSend(initialChatState(), "hi", "typed", "i-1")

    // The reseed page (background/foreground refetch, or web resync mid-send) already contains the
    // persisted user echo for i-1: the bubble must fold into that one row, not survive beside it.
    state = seedTail(state, { events: [userEcho(5, "hi", "i-1")], cursor: null })

    expect(users(state)).toHaveLength(1)
    expect(users(state)[0]?.id).toBe(5)
    expect(users(state)[0]?.send_state).toBeUndefined()
    expect(state.pendingIntents.has("i-1")).toBe(false)
  })

  it("seedTail does not duplicate rows already present by id and later dedups a replayed append", () => {
    let state = seedTail(initialChatState(), { events: [chat(1, "a")], cursor: null })
    ;({ state } = foldLiveEvent(state, chat(2, "b")))
    state = commitPacedChat(state, chat(2, "b"))
    expect(state.messages).toHaveLength(2)

    // Resync refetches the newest page carrying both rows; the reseed must not duplicate them.
    state = seedTail(state, { events: [chat(1, "a"), chat(2, "b")], cursor: null })
    expect(state.messages.map((m) => m.type)).toEqual(["chat", "chat"])

    // A replayed append for an id already in the reseeded tail is deduped away.
    const replay = foldLiveEvent(state, chat(2, "b"))
    expect(replay.paced).toBe(false)
    expect(replay.state.messages).toHaveLength(2)
  })

  it("keeps retained older pages before the newest tail when a reconnect reseeds", () => {
    let state = seedTail(initialChatState(), {
      events: [chat(3, "c"), chat(4, "d")],
      cursor: 3,
    })
    state = prependPage(state, [chat(1, "a"), chat(2, "b")], 1)

    // The reconnect page overlaps the old tail and includes one message that arrived since it.
    // Retained ids 1-2 are older, so they must not be appended after the newest page.
    state = seedTail(state, {
      events: [chat(3, "c"), chat(4, "d"), chat(5, "e")],
      cursor: 3,
    })

    expect(state.messages.map((message) => message.id)).toEqual([1, 2, 3, 4, 5])
    expect(state.messages.at(-1)?.id).toBe(5)
    expect(state.cursor).toBe(1)
  })

  it("restarts paging from the reseed page when the disconnect outran a whole page", () => {
    let state = seedTail(initialChatState(), {
      events: [chat(1, "a"), chat(2, "b")],
      cursor: null,
    })

    // Nothing on the reconnect page overlaps what is held, so ids 3-9 are a hole between them that
    // no cursor reaches. Keeping 1-2 would show them under that hole; drop them and page from 10.
    state = seedTail(state, { events: [chat(10, "j"), chat(11, "k")], cursor: 10 })

    expect(state.messages.map((message) => message.id)).toEqual([10, 11])
    expect(state.cursor).toBe(10)
  })

  it("preserves a pending optimistic bubble across a resync reseed and confirms its later echo", () => {
    let state = beginSend(initialChatState(), "hi", "typed", "i-1")

    // Resync refetches an empty page (the send is not yet persisted); the bubble must survive.
    state = seedTail(state, { events: [], cursor: null })
    expect(users(state)).toHaveLength(1)
    expect(users(state)[0]).toMatchObject({ send_state: "sending" })

    // The later echo confirms the surviving bubble: no vanish, no duplicate.
    ;({ state } = foldLiveEvent(state, userEcho(5, "hi", "i-1")))
    expect(users(state)).toHaveLength(1)
    expect(users(state)[0]?.send_state).toBeUndefined()
  })

  it("markSend toggles a bubble's send_state and clears it when undefined", () => {
    let state = beginSend(initialChatState(), "hi", "typed", "i-1")
    state = markSend(state, "i-1", "failed")
    expect(users(state)[0]?.send_state).toBe("failed")
    state = markSend(state, "i-1", "sending")
    expect(users(state)[0]?.send_state).toBe("sending")
    state = markSend(state, "i-1", undefined)
    expect(users(state)[0]?.send_state).toBeUndefined()
  })

  it("prependPage prepends an older page and records its ids for dedup", () => {
    let state = seedTail(initialChatState(), { events: [chat(3, "c")], cursor: 3 })
    state = prependPage(state, [chat(1, "a"), chat(2, "b")], 1)
    expect(state.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual(["a", "b", "c"])
    expect(state.cursor).toBe(1)
    const replay = foldLiveEvent(state, chat(1, "a"))
    expect(replay.state.messages).toHaveLength(3)
  })

  it("does not mutate the input state", () => {
    const state = initialChatState()
    const next = beginSend(state, "hi", "typed", "i-1")
    expect(state.messages).toHaveLength(0)
    expect(state.pendingIntents.size).toBe(0)
    expect(next).not.toBe(state)
  })

  it("trimTail drops older rows, restores the cursor, and shrinks the dedup set", () => {
    let state = seedTail(initialChatState(), {
      events: [chat(10, "a"), chat(11, "b"), chat(12, "c"), chat(13, "d")],
      cursor: 10,
    })
    state = prependPage(state, [chat(5, "old"), chat(6, "older")], 5)
    const trimmed = trimTail(state, 3)
    expect(trimmed.messages.map((m) => m.id)).toEqual([11, 12, 13])
    expect(trimmed.cursor).toBe(11)
    expect(trimmed.shownIds.has(5)).toBe(false)
    expect(trimmed.shownIds.has(11)).toBe(true)
  })

  it("trimTail keeps an optimistic bubble in the retained tail", () => {
    let state = seedTail(initialChatState(), {
      events: [chat(10, "a"), chat(11, "b"), chat(12, "c")],
      cursor: null,
    })
    state = beginSend(state, "hi", "typed", "i-1")
    const trimmed = trimTail(state, 2)
    expect(trimmed.messages.map((m) => m.id)).toEqual([12, undefined])
    expect(trimmed.cursor).toBe(12)
    expect(trimmed.pendingIntents.has("i-1")).toBe(true)
  })

  it("trimTail is a no-op at or under the keep size", () => {
    const state = seedTail(initialChatState(), {
      events: [chat(10, "a"), chat(11, "b")],
      cursor: null,
    })
    expect(trimTail(state, 2)).toBe(state)
  })

  it("trimTail is a no-op when no retained row has a persisted id", () => {
    let state = initialChatState()
    state = beginSend(state, "hi", "typed", "i-1")
    state = beginSend(state, "yo", "typed", "i-2")
    expect(trimTail(state, 1)).toBe(state)
  })
})

describe("attachments on the stream", () => {
  const ATTACHMENT = { id: "srv1", name: "photo.jpg", mime: "image/jpeg", size: 9 }

  it("beginSend carries attachment metadata onto the optimistic bubble", () => {
    const state = beginSend(initialChatState(), "look", "typed", "i-att", [ATTACHMENT])
    const bubble = state.messages[0]
    if (bubble?.type !== "user") throw new Error("expected a user bubble")
    expect(bubble.attachments).toEqual([ATTACHMENT])
    expect(bubble.send_state).toBe("sending")
  })

  it("the echo's attachment metadata is authoritative on confirmation", () => {
    const begun = beginSend(initialChatState(), "look", "typed", "i-att", [ATTACHMENT])
    const echoed = { ...ATTACHMENT, width: 100, height: 50 }
    const { state } = foldLiveEvent(begun, {
      type: "user",
      id: 7,
      ts: "2026-08-30T00:00:00Z",
      text: "look",
      intent_id: "i-att",
      attachments: [echoed],
    })
    const bubble = state.messages[0]
    if (bubble?.type !== "user") throw new Error("expected a user bubble")
    expect(bubble.attachments).toEqual([echoed])
    expect(bubble.id).toBe(7)
    expect(bubble.send_state).toBeUndefined()
  })
})

describe("retryableSends", () => {
  it("collects only retry-state bubbles as idempotent re-post inputs", () => {
    const attachment = { id: "srv1", name: "a.png", mime: "image/png", size: 1 }
    let state = beginSend(initialChatState(), "one", "typed", "i-1", [attachment])
    state = beginSend(state, "two", "voice", "i-2")
    state = beginSend(state, "three", "typed", "i-3")
    state = markSend(state, "i-1", "retry")
    state = markSend(state, "i-3", "failed")

    expect(retryableSends(state)).toEqual([
      { intentId: "i-1", text: "one", inputMethod: "typed", attachments: [attachment] },
    ])
  })
})
