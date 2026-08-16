import { describe, expect, it } from "vitest";
import {
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  prependPage,
  seedTail,
  type ChatMessage,
  type ChatState,
  type VestaEvent,
} from "@vesta/core";
import type { ConnectionConfig } from "@/api/types";
import { connectionKeyOf } from "@/session/session-model";
import { agentHoldKey, createKeyedHoldStore } from "./keyed-hold";

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

describe("keyed hold store", () => {
  it("holds the chat tail across a controller epoch and merges a fresh seed by id", () => {
    const store = createKeyedHoldStore<ChatState>();
    const key = agentHoldKey("ada", GW);
    store.persist(key, tailWith([1, "a"], [2, "b"]));

    // Foreground: the same key seeds the held tail immediately (stale), no skeleton.
    const seed = store.read(key);
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
    const store = createKeyedHoldStore<ChatState>();
    const key = agentHoldKey("ada", GW);
    let state = tailWith([3, "c"]);
    state = prependPage(state, [chat(1, "a"), chat(2, "b")], 1);
    store.persist(key, state);

    const seed = store.read(key);
    if (!seed) throw new Error("expected held state");
    expect(seed.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(seed.cursor).toBe(1);
  });

  it("keeps each agent's conversation in its own cell across switches", () => {
    const store = createKeyedHoldStore<ChatState>();
    store.persist(agentHoldKey("ada", GW), tailWith([1, "a"]));
    store.persist(agentHoldKey("ben", GW), tailWith([2, "b"]));

    const ada = store.read(agentHoldKey("ada", GW));
    const ben = store.read(agentHoldKey("ben", GW));
    expect(ada?.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual(["a"]);
    expect(ben?.messages.map((m) => (m.type === "chat" ? m.text : ""))).toEqual(["b"]);
  });

  it("a connection (gateway) switch never reads another gateway's cell", () => {
    const store = createKeyedHoldStore<ChatState>();
    store.persist(agentHoldKey("ada", GW), tailWith([1, "a"]));
    const otherGateway = connectionKeyOf(connection("https://gw-b")) ?? "";
    expect(store.read(agentHoldKey("ada", otherGateway))).toBeNull();
  });

  it("preserves a pending optimistic bubble across the epoch and confirms its echo after foreground", () => {
    const store = createKeyedHoldStore<ChatState>();
    const key = agentHoldKey("ada", GW);
    store.persist(key, beginSend(initialChatState(), "hi", "typed", "i-1"));

    // Foreground seeds the surviving optimistic bubble (still sending, intent still pending).
    const seed = store.read(key);
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

  it("an empty store seeds nothing", () => {
    const store = createKeyedHoldStore<ChatState>();
    expect(store.read(agentHoldKey("ada", GW))).toBeNull();
  });

  it("evicts only the least recently written cell past the cap", () => {
    const store = createKeyedHoldStore<number>();
    for (let index = 0; index < 12; index += 1) {
      store.persist(`k${String(index)}`, index);
    }
    // Rewriting k0 refreshes it, so the next eviction takes k1.
    store.persist("k0", 100);
    store.persist("k12", 12);
    expect(store.read("k0")).toBe(100);
    expect(store.read("k1")).toBeNull();
    expect(store.read("k12")).toBe(12);
  });
});
