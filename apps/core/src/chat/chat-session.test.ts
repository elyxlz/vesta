import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type HttpClient } from "../transport/http";
import type { SocketLike } from "../transport/websocket";
import { PACING } from "../pacing/pacing";
import type { VestaEvent } from "../protocol/events";
import {
  SEED_RETRY_BASE_MS,
  createChatSession,
  type ChatSession,
  type ChatSessionCallbacks,
} from "./chat-session";
import { initialChatState, type HistoryPage } from "./chat-stream-model";

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  readonly url: string;
  constructor(url: string) {
    this.url = url;
  }
  send(): void {
    // The chat socket's outbound frames are covered at the socket.
  }
  close(): void {
    this.closed = true;
  }
}

// The longest typing delay pacing can produce, so a paced message is guaranteed to have landed
// after it whatever the randomised jitter chose.
const MAX_TYPING_DELAY_MS = PACING.max * (1 + PACING.variance);

interface SentBody {
  text?: string;
  attachments?: string[];
  intent_id: string;
}

interface Harness {
  sockets: FakeSocket[];
  posts: SentBody[];
  history: ReturnType<typeof vi.fn<(cursor?: number) => Promise<HistoryPage>>>;
  pacing: { natural: boolean };
  callbacks: {
    onReply: ReturnType<typeof vi.fn<(text: string) => void>>;
    onPrefetch: ReturnType<typeof vi.fn<(text: string) => void>>;
  };
  start: (initialState?: ReturnType<typeof initialChatState>) => ChatSession;
  rejectNextPost: (error: Error) => void;
}

function harness(): Harness {
  const sockets: FakeSocket[] = [];
  const posts: SentBody[] = [];
  let nextPostFailure: Error | null = null;
  let nextId = 0;
  let builds = 0;
  const http: HttpClient = {
    request: () => Promise.reject(new Error("unused")),
    json: <T>(_path: string, init?: RequestInit) => {
      const body = typeof init?.body === "string" ? init.body : "{}";
      posts.push(JSON.parse(body) as SentBody);
      if (nextPostFailure !== null) {
        const failure = nextPostFailure;
        nextPostFailure = null;
        return Promise.reject(failure);
      }
      return Promise.resolve({} as T);
    },
  };
  const history = vi.fn<(cursor?: number) => Promise<HistoryPage>>();
  history.mockResolvedValue({ events: [], cursor: null });
  const pacing = { natural: true };
  const callbacks: ChatSessionCallbacks & Harness["callbacks"] = {
    onReply: vi.fn<(text: string) => void>(),
    onPrefetch: vi.fn<(text: string) => void>(),
  };
  return {
    sockets,
    posts,
    history,
    pacing,
    callbacks,
    start: (initialState) =>
      createChatSession(
        {
          http,
          agent: "ada",
          buildUrl: () => {
            builds += 1;
            return Promise.resolve(
              `wss://vestad.test/agents/ada/chat/ws?token=access-${String(builds)}`,
            );
          },
          createSocket: (url) => {
            const socket = new FakeSocket(url);
            sockets.push(socket);
            return socket;
          },
          fetchHistory: history,
          makeId: () => {
            nextId += 1;
            return `intent-${String(nextId)}`;
          },
          naturalPacing: () => pacing.natural,
          initialState,
        },
        callbacks,
      ),
    rejectNextPost: (error) => {
      nextPostFailure = error;
    },
  };
}

// Drain every pending microtask (the async URL build, the history seed, a settled POST).
const settle = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};

// Open the newest chat socket (the reseed trigger) and let the session settle.
async function openAndFlush(h: Harness): Promise<void> {
  await settle();
  const socket = h.sockets.at(-1);
  if (!socket?.onopen) throw new Error("chat socket not constructed");
  socket.onopen();
  await settle();
}

function deliver(h: Harness, event: VestaEvent): void {
  h.sockets.at(-1)?.onmessage?.(JSON.stringify(event));
}

function chat(id: number, text: string): VestaEvent {
  return { type: "chat", text, id, ts: "2026-01-01T00:00:00Z" };
}

function userEcho(id: number, text: string, intentId: string): VestaEvent {
  return { type: "user", text, id, intent_id: intentId };
}

const users = (session: ChatSession) =>
  session.getState().chat.messages.filter((m) => m.type === "user");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createChatSession", () => {
  it("dials the token-stamped chat socket and hydrates the newest history page", async () => {
    const h = harness();
    h.history.mockResolvedValue({ events: [chat(1, "hello")], cursor: null });
    const session = h.start();
    await openAndFlush(h);

    expect(h.sockets).toHaveLength(1);
    expect(h.sockets[0]?.url).toBe(
      "wss://vestad.test/agents/ada/chat/ws?token=access-1",
    );
    expect(h.history).toHaveBeenCalledWith();
    const state = session.getState();
    expect(state.chat.historyLoaded).toBe(true);
    expect(state.chat.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(state.socket).toBe("open");
    expect(state.reseedRevision).toBe(1);
  });

  // The history fetch needs only the Bearer header, so it runs in parallel with the socket
  // handshake instead of waiting for "open": the tail renders after one round trip.
  it("seeds history at creation without waiting for the socket to open", async () => {
    const h = harness();
    h.history.mockResolvedValue({ events: [chat(1, "hello")], cursor: null });
    const session = h.start();
    await settle();
    expect(session.getState().chat.historyLoaded).toBe(true);
    expect(h.sockets.at(-1)?.onopen).not.toBeNull();
  });

  it("does not refetch on the first open after the creation seed landed", async () => {
    const h = harness();
    h.start();
    await openAndFlush(h);
    expect(h.history).toHaveBeenCalledTimes(1);
  });

  it("reseeds on the first open when the creation seed failed", async () => {
    const h = harness();
    h.history
      .mockRejectedValueOnce(new Error("gateway hiccup"))
      .mockResolvedValueOnce({ events: [chat(1, "hello")], cursor: null });
    const session = h.start();
    await openAndFlush(h);
    expect(h.history).toHaveBeenCalledTimes(2);
    expect(session.getState().chat.historyLoaded).toBe(true);
  });

  it("retries a failed seed on a capped backoff while the socket stays open", async () => {
    const h = harness();
    h.history
      .mockRejectedValueOnce(new Error("first"))
      .mockRejectedValueOnce(new Error("second"))
      .mockResolvedValue({ events: [chat(1, "hello")], cursor: null });
    const session = h.start();
    await openAndFlush(h);
    expect(h.history).toHaveBeenCalledTimes(2);
    expect(session.getState().chat.historyLoaded).toBe(false);
    await vi.advanceTimersByTimeAsync(SEED_RETRY_BASE_MS);
    expect(h.history).toHaveBeenCalledTimes(3);
    expect(session.getState().chat.historyLoaded).toBe(true);
  });

  it("stops retrying a seed once the socket closes, and reseeds on the next open", async () => {
    const h = harness();
    h.history.mockRejectedValue(new Error("down"));
    h.start();
    await openAndFlush(h);
    h.sockets[0]?.onclose?.();
    await vi.advanceTimersByTimeAsync(SEED_RETRY_BASE_MS);
    // The seed at creation, then the one on open; no retry after the close.
    expect(h.history).toHaveBeenCalledTimes(2);
    h.history.mockResolvedValue({ events: [], cursor: null });
    await vi.advanceTimersByTimeAsync(1000);
    h.sockets[1]?.onopen?.();
    await settle();
    expect(h.history).toHaveBeenCalledTimes(3);
  });

  it("reseeds on every later open so a reconnect gap self-heals", async () => {
    const h = harness();
    h.start();
    await openAndFlush(h);
    h.sockets[0]?.onclose?.();
    await vi.advanceTimersByTimeAsync(1000);
    h.sockets[1]?.onopen?.();
    await settle();
    expect(h.history).toHaveBeenCalledTimes(2);
  });

  it("renders the held state at once and merges the seed into it by id", async () => {
    const h = harness();
    const held = {
      ...initialChatState(),
      messages: [chat(1, "held")],
      shownIds: new Set([1]),
    };
    h.history.mockResolvedValue({
      events: [chat(1, "held"), chat(2, "fresh")],
      cursor: null,
    });
    const session = h.start(held);
    expect(session.getState().chat.messages).toHaveLength(1);
    await openAndFlush(h);
    expect(session.getState().chat.messages.map((m) => m.id)).toEqual([1, 2]);
  });

  it("sends an optimistic bubble and confirms it on the chat-socket echo", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);

    session.send("hi");
    await settle();
    expect(users(session)).toHaveLength(1);
    expect(users(session)[0]).toMatchObject({
      text: "hi",
      send_state: "sending",
    });

    deliver(h, userEcho(5, "hi", h.posts[0]?.intent_id ?? ""));
    expect(users(session)).toHaveLength(1);
    expect(users(session)[0]?.send_state).toBeUndefined();
  });

  it("keeps the bubble and marks it retry when the send POST returns 503", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);
    h.rejectNextPost(new ApiError(503, "unavailable"));
    session.send("retryable");
    await settle();
    expect(users(session)[0]).toMatchObject({
      text: "retryable",
      send_state: "retry",
    });
  });

  it("retries a failed send under its original intent id and confirms on the echo", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);
    h.rejectNextPost(new ApiError(503, "unavailable"));
    session.send("again");
    await settle();
    const intentId = h.posts[0]?.intent_id ?? "";

    session.retry(intentId, "again");
    expect(users(session)[0]).toMatchObject({ send_state: "sending" });
    await settle();
    expect(h.posts).toHaveLength(2);
    expect(h.posts[1]?.intent_id).toBe(intentId);
    deliver(h, userEcho(9, "again", intentId));
    expect(users(session)).toHaveLength(1);
    expect(users(session)[0]?.send_state).toBeUndefined();
  });

  it("re-posts a retry-state bubble under its original id on every open, including the first", async () => {
    const h = harness();
    const attachment = {
      id: "att1",
      name: "photo.jpg",
      mime: "image/jpeg",
      size: 9,
    };
    const session = h.start();
    await openAndFlush(h);
    h.rejectNextPost(new ApiError(503, "unavailable"));
    session.send("stuck", "typed", [attachment]);
    await settle();
    expect(users(session)[0]).toMatchObject({ send_state: "retry" });
    const intentId = h.posts[0]?.intent_id ?? "";

    h.sockets[0]?.onclose?.();
    await vi.advanceTimersByTimeAsync(1000);
    // The re-post fails again, so the bubble parks again for the next open.
    h.rejectNextPost(new ApiError(503, "unavailable"));
    h.sockets[1]?.onopen?.();
    expect(h.posts).toHaveLength(2);
    expect(h.posts[1]).toMatchObject({
      intent_id: intentId,
      attachments: ["att1"],
    });
    expect(users(session)[0]).toMatchObject({ send_state: "sending" });
    await settle();
    expect(users(session)[0]).toMatchObject({ send_state: "retry" });

    // A held state carrying a parked bubble re-posts on the very first open of a new session.
    const parked = h.start(session.getState().chat);
    await openAndFlush(h);
    expect(h.posts).toHaveLength(3);
    expect(h.posts[2]?.intent_id).toBe(intentId);
    parked.close();
  });

  it("prepends older history on loadMore and defers trimming while a load is in flight", async () => {
    const h = harness();
    const seeded = Array.from({ length: 120 }, (_, i) =>
      chat(100 + i, `m${String(i)}`),
    );
    h.history.mockResolvedValue({ events: seeded, cursor: 100 });
    const session = h.start();
    await openAndFlush(h);
    expect(session.getState().chat.cursor).toBe(100);

    let resolveOlder: (page: HistoryPage) => void = () => undefined;
    h.history.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOlder = resolve;
      }),
    );
    const load = session.loadMore();
    expect(h.history).toHaveBeenLastCalledWith(100);
    expect(session.getState().loadingMore).toBe(true);

    session.trimHistory();
    expect(session.getState().chat.messages).toHaveLength(120);

    resolveOlder({ events: [chat(50, "old")], cursor: null });
    await load;
    const state = session.getState();
    expect(state.chat.messages[0]).toMatchObject({ id: 50, text: "old" });
    expect(state.chat.messages).toHaveLength(121);
    expect(state.chat.cursor).toBeNull();
    expect(state.loadingMore).toBe(false);

    session.trimHistory();
    expect(session.getState().chat.messages.length).toBeLessThan(121);
    expect(session.getState().chat.cursor).not.toBeNull();
  });

  it("paces a live reply, toggling typing and firing onReply on commit", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);

    deliver(h, chat(7, "pong"));
    expect(session.getState().typing).toBe(true);
    expect(session.getState().chat.messages).toHaveLength(0);
    expect(h.callbacks.onPrefetch).toHaveBeenCalledWith("pong");
    expect(h.callbacks.onReply).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(MAX_TYPING_DELAY_MS);
    expect(session.getState().chat.messages.map((m) => m.type)).toEqual([
      "chat",
    ]);
    expect(session.getState().typing).toBe(false);
    expect(session.getState().latestReply).toBe("pong");
    expect(h.callbacks.onReply).toHaveBeenCalledWith("pong");
  });

  // Pacing is a feel, not a contract: with natural pacing off every event commits at once, and a
  // burst past the flush threshold is dumped after the first delay rather than typed out one by one.
  it("commits at once with natural pacing off", async () => {
    const h = harness();
    h.pacing.natural = false;
    const session = h.start();
    await openAndFlush(h);
    deliver(h, chat(7, "pong"));
    expect(session.getState().chat.messages).toHaveLength(1);
    expect(session.getState().typing).toBe(false);
    expect(h.callbacks.onReply).toHaveBeenCalledWith("pong");
  });

  it("flushes a burst past the threshold after one typing delay", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);
    const burst = PACING.flushThreshold + 2;
    for (let i = 0; i < burst; i++) deliver(h, chat(10 + i, `m${String(i)}`));
    expect(session.getState().chat.messages).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(MAX_TYPING_DELAY_MS);
    expect(session.getState().chat.messages).toHaveLength(burst);
    expect(session.getState().typing).toBe(false);
  });

  it("flushPacing commits the queue at once", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);
    deliver(h, chat(7, "pong"));
    expect(session.getState().typing).toBe(true);
    session.flushPacing();
    expect(session.getState().chat.messages).toHaveLength(1);
    expect(session.getState().typing).toBe(false);
  });

  it("drops a pending paced reply and stops every timer on close", async () => {
    const h = harness();
    const session = h.start();
    await openAndFlush(h);
    deliver(h, chat(7, "pong"));
    session.close();
    expect(h.sockets[0]?.closed).toBe(true);
    expect(session.getState().socket).toBe("closed");
    expect(vi.getTimerCount()).toBe(0);
    expect(h.callbacks.onReply).not.toHaveBeenCalled();
  });
});
