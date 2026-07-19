import type { InputMethod, VestaEvent } from "../protocol/events"
import { PACING } from "../pacing/pacing"

export type SendState = "sending" | "retry" | "failed"

// A chat row as the view holds it. Core's VestaEvent is the wire shape (server `id` always present);
// a view row may instead be an optimistic user bubble (no persisted id yet) carrying `intent_id` /
// `send_state` to track its unconfirmed POST until the append echo confirms it. `id` is optional on
// every member so an optimistic bubble (no id yet) is representable.
type LooseId<T> = T extends unknown ? Omit<T, "id"> & { id?: number } : never
export type ChatMessage =
  | Exclude<LooseId<VestaEvent>, { type: "user" }>
  | (Extract<LooseId<VestaEvent>, { type: "user" }> & {
      intent_id?: string
      send_state?: SendState
    })

export interface HistoryPage {
  events: ChatMessage[]
  cursor: number | null
}

export interface ChatState {
  messages: ChatMessage[]
  // Ids of persisted events already in `messages`, so a live append that races the history fetch
  // (or a resync refetch) never duplicates a row.
  shownIds: Set<number>
  // Intent ids of optimistic bubbles awaiting their append echo (delivery truth is the echo).
  pendingIntents: Set<string>
  cursor: number | null
  historyLoaded: boolean
}

export function initialChatState(): ChatState {
  return {
    messages: [],
    shownIds: new Set(),
    pendingIntents: new Set(),
    cursor: null,
    historyLoaded: false,
  }
}

function capTail(messages: ChatMessage[]): ChatMessage[] {
  return messages.length > PACING.maxMessages ? messages.slice(-PACING.maxMessages) : messages
}

// Merge the newest history page and MERGE, never replace: a live row that raced the fetch (id absent
// from the page) and an optimistic bubble still awaiting its echo both survive, so no delivered or
// in-flight message is dropped. An optimistic bubble whose intent already appears as a persisted user
// echo ON the page is instead dropped and its intent cleared: that echo IS the confirmation, so it
// must not survive as a duplicate "sending" twin (mobile background/foreground, web resync-mid-send).
// shownIds is unioned with the page ids. Serves the initial load and a resync alike.
export function seedTail(state: ChatState, page: HistoryPage): ChatState {
  const pageIds = new Set<number>()
  const echoedIntents = new Set<string>()
  for (const event of page.events) {
    if (event.id != null) pageIds.add(event.id)
    if (event.type === "user" && event.intent_id != null) echoedIntents.add(event.intent_id)
  }
  const survivors = state.messages.filter(
    (message) =>
      (message.type === "user" &&
        message.intent_id != null &&
        state.pendingIntents.has(message.intent_id) &&
        !echoedIntents.has(message.intent_id)) ||
      (message.id != null && !pageIds.has(message.id)),
  )
  const pendingIntents = new Set(state.pendingIntents)
  for (const intentId of echoedIntents) pendingIntents.delete(intentId)
  const shownIds = new Set(state.shownIds)
  for (const id of pageIds) shownIds.add(id)
  return {
    ...state,
    messages: capTail([...page.events, ...survivors]),
    shownIds,
    pendingIntents,
    cursor: page.cursor,
    historyLoaded: true,
  }
}

// Fold one live event: confirm an optimistic user bubble by intent_id (clear send_state, adopt
// id/ts), dedup a persisted row by event id, otherwise append. A live `chat` is not appended here;
// it is flagged `paced` so the hook routes it through the typing delay and commits it on drain.
export function foldLiveEvent(
  state: ChatState,
  event: ChatMessage,
): { state: ChatState; paced: boolean } {
  if (
    event.type === "user" &&
    event.intent_id != null &&
    state.pendingIntents.has(event.intent_id)
  ) {
    const intentId = event.intent_id
    const pendingIntents = new Set(state.pendingIntents)
    pendingIntents.delete(intentId)
    const shownIds = new Set(state.shownIds)
    if (event.id != null) shownIds.add(event.id)
    const messages = state.messages.map((message) =>
      message.type === "user" && message.intent_id === intentId
        ? {
            ...message,
            send_state: undefined,
            id: event.id ?? message.id,
            ts: event.ts ?? message.ts,
          }
        : message,
    )
    return { state: { ...state, messages, shownIds, pendingIntents }, paced: false }
  }

  if (event.id != null) {
    if (state.shownIds.has(event.id)) return { state, paced: false }
    const shownIds = new Set(state.shownIds)
    shownIds.add(event.id)
    if (event.type === "chat") return { state: { ...state, shownIds }, paced: true }
    return {
      state: { ...state, shownIds, messages: capTail([...state.messages, event]) },
      paced: false,
    }
  }

  if (event.type === "chat") return { state, paced: true }
  return { state: { ...state, messages: capTail([...state.messages, event]) }, paced: false }
}

// Commit a paced `chat` to the tail once the hook's typing delay has elapsed. Its dedup entry was
// already recorded by foldLiveEvent, so this only appends (the twin of web's drain append).
export function commitPacedChat(state: ChatState, event: ChatMessage): ChatState {
  return { ...state, messages: capTail([...state.messages, event]) }
}

// Optimistic send: register the intent and push a user bubble tagged { intent_id, send_state:
// "sending" } that its append echo will later confirm.
export function beginSend(
  state: ChatState,
  text: string,
  inputMethod: InputMethod,
  intentId: string,
): ChatState {
  const pendingIntents = new Set(state.pendingIntents)
  pendingIntents.add(intentId)
  const bubble: ChatMessage = {
    type: "user",
    text,
    input_method: inputMethod,
    intent_id: intentId,
    send_state: "sending",
    ts: new Date().toISOString(),
  }
  return { ...state, pendingIntents, messages: capTail([...state.messages, bubble]) }
}

// Set (or clear, when `send` is undefined) a bubble's send_state by intent id.
export function markSend(
  state: ChatState,
  intentId: string,
  send: SendState | undefined,
): ChatState {
  const messages = state.messages.map((message) =>
    message.type === "user" && message.intent_id === intentId
      ? { ...message, send_state: send }
      : message,
  )
  return { ...state, messages }
}

// Prepend an older history page for loadMore, recording its ids for dedup. Unlike the tail, older
// pages are not capped: loadMore grows the visible history upward on demand.
export function prependPage(
  state: ChatState,
  events: ChatMessage[],
  cursor: number | null,
): ChatState {
  const shownIds = new Set(state.shownIds)
  for (const event of events) if (event.id != null) shownIds.add(event.id)
  return { ...state, shownIds, messages: [...events, ...state.messages], cursor }
}
