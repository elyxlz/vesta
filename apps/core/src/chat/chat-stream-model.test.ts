import { describe, expect, it } from "vitest"
import type { VestaEvent } from "../protocol/events"
import {
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
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
})
