import type { ChatAttachment } from "../attachments/attachment-model";
import type { InputMethod, VestaEvent } from "../protocol/events";
import { PACING } from "../pacing/pacing";

export type SendState = "sending" | "retry" | "failed";

// A chat row as the view holds it. Core's VestaEvent is the wire shape (server `id` always present);
// a view row may instead be an optimistic user bubble (no persisted id yet) carrying `intent_id` /
// `send_state` to track its unconfirmed POST until the append echo confirms it. `id` is optional on
// every member so an optimistic bubble (no id yet) is representable.
type LooseId<T> = T extends unknown ? Omit<T, "id"> & { id?: number } : never;
export type ChatMessage =
  | Exclude<LooseId<VestaEvent>, { type: "user" }>
  | (Extract<LooseId<VestaEvent>, { type: "user" }> & {
      send_state?: SendState;
    });

export interface HistoryPage {
  events: ChatMessage[];
  cursor: number | null;
}

export interface ChatState {
  messages: ChatMessage[];
  // Ids of persisted events already in `messages`, so a live append that races the history fetch
  // (or a resync refetch) never duplicates a row.
  shownIds: Set<number>;
  // Intent ids of optimistic bubbles awaiting their append echo (delivery truth is the echo).
  pendingIntents: Set<string>;
  cursor: number | null;
  historyLoaded: boolean;
}

export function initialChatState(): ChatState {
  return {
    messages: [],
    shownIds: new Set(),
    pendingIntents: new Set(),
    cursor: null,
    historyLoaded: false,
  };
}

function capTail(messages: ChatMessage[]): ChatMessage[] {
  return messages.length > PACING.maxMessages
    ? messages.slice(-PACING.maxMessages)
    : messages;
}

// Merge the newest history page, never replace: a live row that raced the fetch and an optimistic
// bubble still awaiting its echo both survive, so no delivered or in-flight message is dropped. A
// bubble whose intent already appears as a persisted echo ON the page folds into it, since that echo
// IS the confirmation and must not survive as a duplicate "sending" twin (mobile background, web
// resync-mid-send). Ids are handed out in order, so every retained row is either older than the whole
// page or newer than every row on it: older rows, then the page, then live races and bubbles. The
// loaded older-page cursor is kept, so a resync does not refetch and prepend history already held.
// shownIds is unioned with the page ids. Serves the initial load and a resync alike.
export function seedTail(state: ChatState, page: HistoryPage): ChatState {
  const index = indexPage(page);
  const { older, newer, overlaps } = partitionHeld(state, index);

  // Older rows the page does not reach sit above a hole no cursor can page into (a disconnect longer
  // than one page), so they are dropped and paging restarts from the page's own cursor.
  const joined = older.length === 0 || overlaps;
  const pendingIntents = new Set(state.pendingIntents);
  for (const intentId of index.echoedIntents) pendingIntents.delete(intentId);
  const shownIds = new Set(state.shownIds);
  for (const id of index.pageIds) shownIds.add(id);
  return {
    ...state,
    messages: capTail([...(joined ? older : []), ...page.events, ...newer]),
    shownIds,
    pendingIntents,
    cursor: joined && state.historyLoaded ? state.cursor : page.cursor,
    historyLoaded: true,
  };
}

interface PageIndex {
  pageIds: Set<number>;
  echoedIntents: Set<string>;
  oldestPageId: number | null;
}

function indexPage(page: HistoryPage): PageIndex {
  const index: PageIndex = {
    pageIds: new Set(),
    echoedIntents: new Set(),
    oldestPageId: null,
  };
  for (const event of page.events) {
    if (event.id != null) {
      index.pageIds.add(event.id);
      if (index.oldestPageId == null || event.id < index.oldestPageId)
        index.oldestPageId = event.id;
    }
    if (event.type === "user" && event.intent_id != null)
      index.echoedIntents.add(event.intent_id);
  }
  return index;
}

// Sort the rows already held around the page: rows older than it, rows newer than it (including the
// pending bubbles the page has not echoed), and whether any held row overlaps the page at all.
function partitionHeld(
  state: ChatState,
  index: PageIndex,
): { older: ChatMessage[]; newer: ChatMessage[]; overlaps: boolean } {
  const older: ChatMessage[] = [];
  const newer: ChatMessage[] = [];
  let overlaps = false;
  for (const message of state.messages) {
    const intentId = message.type === "user" ? message.intent_id : undefined;
    const pending = intentId != null && state.pendingIntents.has(intentId);
    if (pending && index.echoedIntents.has(intentId)) continue;
    if (message.id == null) {
      if (pending) newer.push(message);
      continue;
    }
    if (index.pageIds.has(message.id)) {
      overlaps = true;
      continue;
    }
    if (index.oldestPageId != null && message.id < index.oldestPageId)
      older.push(message);
    else newer.push(message);
  }
  return { older, newer, overlaps };
}

// Tool-call events ride the wire (Debug, agent-internal) but never appear in the chat list: the
// conversation is the person, not the machinery. Filtered at the live-fold entry so no tool row ever
// enters `messages`; history pages from the chat service are already pure conversation.
function isChatRow(event: ChatMessage): boolean {
  return event.type !== "tool_start" && event.type !== "tool_end";
}

// Fold one live event: confirm an optimistic user bubble by intent_id (clear send_state, adopt
// id/ts), dedup a persisted row by event id, otherwise append. A live `chat` is not appended here;
// it is flagged `paced` so the hook routes it through the typing delay and commits it on drain.
export function foldLiveEvent(
  state: ChatState,
  event: ChatMessage,
): { state: ChatState; paced: boolean } {
  if (!isChatRow(event)) return { state, paced: false };
  if (
    event.type === "user" &&
    event.intent_id != null &&
    state.pendingIntents.has(event.intent_id)
  ) {
    const intentId = event.intent_id;
    const pendingIntents = new Set(state.pendingIntents);
    pendingIntents.delete(intentId);
    const shownIds = new Set(state.shownIds);
    if (event.id != null) shownIds.add(event.id);
    const messages = state.messages.map((message) =>
      message.type === "user" && message.intent_id === intentId
        ? {
            ...message,
            send_state: undefined,
            id: event.id ?? message.id,
            ts: event.ts ?? message.ts,
            // The persisted echo's attachment metadata is authoritative over the optimistic copy.
            ...(event.attachments ? { attachments: event.attachments } : {}),
          }
        : message,
    );
    return {
      state: { ...state, messages, shownIds, pendingIntents },
      paced: false,
    };
  }

  if (event.id != null) {
    if (state.shownIds.has(event.id)) return { state, paced: false };
    const shownIds = new Set(state.shownIds);
    shownIds.add(event.id);
    if (event.type === "chat")
      return { state: { ...state, shownIds }, paced: true };
    return {
      state: {
        ...state,
        shownIds,
        messages: capTail([...state.messages, event]),
      },
      paced: false,
    };
  }

  if (event.type === "chat") return { state, paced: true };
  return {
    state: { ...state, messages: capTail([...state.messages, event]) },
    paced: false,
  };
}

// Commit a paced `chat` to the tail once the hook's typing delay has elapsed (the twin of web's drain
// append). A reconnect tail refetch can merge this event by id while it still sits in the pacing
// queue, so skip the append when the id is already present in the merged tail: that reseed row is the
// same message, and re-adding it would duplicate the bubble.
export function commitPacedChat(
  state: ChatState,
  event: ChatMessage,
): ChatState {
  if (
    event.id != null &&
    state.messages.some((message) => message.id === event.id)
  )
    return state;
  return { ...state, messages: capTail([...state.messages, event]) };
}

// Optimistic send: register the intent and push a user bubble tagged { intent_id, send_state:
// "sending" } that its append echo will later confirm. Attachment metadata (already finalized
// server-side before any send) rides the bubble so media renders during the in-flight window.
export function beginSend(
  state: ChatState,
  text: string,
  inputMethod: InputMethod,
  intentId: string,
  attachments?: ChatAttachment[],
): ChatState {
  const pendingIntents = new Set(state.pendingIntents);
  pendingIntents.add(intentId);
  const bubble: ChatMessage = {
    type: "user",
    text,
    input_method: inputMethod,
    intent_id: intentId,
    send_state: "sending",
    ts: new Date().toISOString(),
    ...(attachments && attachments.length > 0 ? { attachments } : {}),
  };
  return {
    ...state,
    pendingIntents,
    messages: capTail([...state.messages, bubble]),
  };
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
  );
  return { ...state, messages };
}

// Trim policy, shared by every client: chat views outlive navigation (web pages hide instead of
// unmounting, mobile holds persist the tail across screen pops), so paged-in history would
// otherwise accumulate for the whole session. Settling at the latest message for the settle
// window trims the tail to two pages; scrolling up refetches through the ordinary paging.
const TRIM_HISTORY_KEEP = 100;
export const TRIM_HISTORY_SETTLE_MS = 30_000;

// The inverse of prependPage: drop loaded older history back down to the newest `keep` rows once
// the user has settled at the bottom, so a long-lived chat view does not hold the whole
// conversation forever. The cursor moves to the oldest kept persisted id (ids page exclusively
// below the cursor), so loadMore refetches exactly what was dropped, and the dedup set shrinks to
// the kept range. Optimistic bubbles are the newest rows, so the kept slice always contains them.
export function trimTail(
  state: ChatState,
  keep = TRIM_HISTORY_KEEP,
): ChatState {
  if (state.messages.length <= keep) return state;
  const messages = state.messages.slice(-keep);
  const oldestKeptId = messages.find((message) => message.id != null)?.id;
  if (oldestKeptId == null) return state;
  const shownIds = new Set(
    [...state.shownIds].filter((id) => id >= oldestKeptId),
  );
  return { ...state, messages, shownIds, cursor: oldestKeptId };
}

// Prepend an older history page for loadMore, recording its ids for dedup. Unlike the tail, older
// pages are not capped: loadMore grows the visible history upward on demand.
export function prependPage(
  state: ChatState,
  events: ChatMessage[],
  cursor: number | null,
): ChatState {
  const shownIds = new Set(state.shownIds);
  for (const event of events) if (event.id != null) shownIds.add(event.id);
  return {
    ...state,
    shownIds,
    messages: [...events, ...state.messages],
    cursor,
  };
}

// The bubbles parked in the retryable state, as idempotent re-post inputs. Owned here so every
// client's reconnect edge replays the same delivery semantics (same intent id, dedup-safe).
export interface RetryableSend {
  intentId: string;
  text: string;
  inputMethod: InputMethod;
  attachments?: ChatAttachment[];
}

export function retryableSends(state: ChatState): RetryableSend[] {
  return state.messages.flatMap((message) =>
    message.type === "user" &&
    message.send_state === "retry" &&
    message.intent_id != null
      ? [
          {
            intentId: message.intent_id,
            text: message.text,
            inputMethod: message.input_method ?? "typed",
            ...(message.attachments
              ? { attachments: message.attachments }
              : {}),
          },
        ]
      : [],
  );
}
