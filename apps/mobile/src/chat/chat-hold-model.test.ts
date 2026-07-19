import { describe, expect, it } from "vitest";
import type { VestaEvent } from "@vesta/core";
import type { ConnectionConfig } from "@/api/types";
import { connectionKeyOf } from "@/session/session-model";
import {
  captureChatHold,
  chatHoldKey,
  emptyChatHold,
  heldChatState,
} from "./chat-hold-model";
import {
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  prependPage,
  seedTail,
  type ChatMessage,
  type ChatState,
} from "./chat-stream-model";

function chat(id: number, text: string): VestaEvent {
  return { type: "chat", text, id };
}

function userEcho(id: number, text: string, intentId: string): ChatMessage {
  return { type: "user", text, id, intent_id: intentId } as ChatMessage;
}

function connection(url: string): ConnectionConfig {
  return {
    url,
    accessToken: "t",
    refreshToken: "r",
    expiresAt: 0,
    hosted: false,
  };
}

const GW = connectionKeyOf(connection("https://gw-a")) ?? "";

// A live-then-committed chat, the shape a tail carries by the time the app backgrounds.
function tailWith(...ids: [number, string][]): ChatState {
  let state = initialChatState();
  for (const [id, text] of ids) {
    const { state: folded } = foldLiveEvent(state, chat(id, text));
    state = commitPacedChat(folded, chat(id, text));
  }
  return seedTail(state, { events: [], cursor: 7 });
}

describe("chat hold", () => {
  it("holds the tail across a controller epoch and merges a fresh seed by id", () => {
    const key = chatHoldKey("ada", GW);
    const captured = captureChatHold(key, tailWith([1, "a"], [2, "b"]));

    // Foreground: the same key seeds the held tail immediately (stale), no skeleton.
    const seed = heldChatState(captured, key);
    expect(seed).not.toBeNull();
    if (!seed) throw new Error("expected held state");
    expect(seed.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual([
      "a",
      "b",
    ]);
    expect(seed.historyLoaded).toBe(true);

    // seedTail refetches the newest page carrying both rows: merge by id, no duplicates.
    const merged = seedTail(seed, { events: [chat(1, "a"), chat(2, "b")], cursor: null });
    expect(merged.messages.map((m) => m.type)).toEqual(["chat", "chat"]);
  });

  it("keeps a loadMore-extended history across the epoch", () => {
    const key = chatHoldKey("ada", GW);
    let state = tailWith([3, "c"]);
    state = prependPage(state, [chat(1, "a"), chat(2, "b")], 1);
    const captured = captureChatHold(key, state);

    const seed = heldChatState(captured, key);
    if (!seed) throw new Error("expected held state");
    expect(seed.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(seed.cursor).toBe(1);
  });

  it("clears synchronously on an agent switch so no messages bleed across", () => {
    const captured = captureChatHold(chatHoldKey("ada", GW), tailWith([1, "a"]));
    expect(heldChatState(captured, chatHoldKey("ben", GW))).toBeNull();
  });

  it("clears on a connection (gateway) switch", () => {
    const captured = captureChatHold(chatHoldKey("ada", GW), tailWith([1, "a"]));
    const otherGateway = connectionKeyOf(connection("https://gw-b")) ?? "";
    expect(heldChatState(captured, chatHoldKey("ada", otherGateway))).toBeNull();
  });

  it("preserves a pending optimistic bubble across the epoch and confirms its echo after foreground", () => {
    const key = chatHoldKey("ada", GW);
    const sending = beginSend(initialChatState(), "hi", "typed", "i-1");
    const captured = captureChatHold(key, sending);

    // Foreground seeds the surviving optimistic bubble (still sending, intent still pending).
    const seed = heldChatState(captured, key);
    if (!seed) throw new Error("expected held state");
    expect(seed.pendingIntents.has("i-1")).toBe(true);
    const users = seed.messages.filter((m) => m.type === "user");
    expect(users[0]).toMatchObject({ text: "hi", send_state: "sending" });

    // The later append echo confirms the surviving bubble: no vanish, no duplicate.
    const { state: confirmed } = foldLiveEvent(seed, userEcho(5, "hi", "i-1"));
    const confirmedUsers = confirmed.messages.filter((m) => m.type === "user");
    expect(confirmedUsers).toHaveLength(1);
    expect(confirmedUsers[0]?.send_state).toBeUndefined();
  });

  it("an empty hold seeds nothing", () => {
    expect(heldChatState(emptyChatHold, chatHoldKey("ada", GW))).toBeNull();
  });
});
