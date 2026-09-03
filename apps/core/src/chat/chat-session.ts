import type { ChatAttachment } from "../attachments/attachment-model";
import { fetchChatHistory } from "../api/history";
import type { InputMethod } from "../protocol/events";
import type { HttpClient } from "../transport/http";
import type { SocketLike } from "../transport/websocket";
import { PACING, typingDelay } from "../pacing/pacing";
import { createChatSender, type ChatSender } from "./chat-sender";
import { createChatSocket, type ChatSocketState } from "./chat-socket";
import {
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  prependPage,
  seedTail,
  trimTail,
  type ChatMessage,
  type ChatState,
  type HistoryPage,
} from "./chat-stream-model";

// A failed history seed retries on this capped backoff while the socket stays open, so one blip
// never strands the skeleton; a fetch that fails after the socket closed waits for the next open.
export const SEED_RETRY_BASE_MS = 1_000;
const SEED_RETRY_MAX_MS = 30_000;

export interface ChatSessionDeps {
  http: HttpClient;
  agent: string;
  // Built per connect, so a reconnect hours later dials with a freshly refreshed access token.
  buildUrl: () => Promise<string>;
  // Defaults to the platform WebSocket; tests inject a fake.
  createSocket?: (url: string) => SocketLike;
  // Defaults to the app-chat history route over `http`; tests inject a scripted page.
  fetchHistory?: (cursor?: number) => Promise<HistoryPage>;
  makeId: () => string;
  // Read at each pacing step, so a preference flip lands mid-conversation. False commits every
  // reply at once (a voice conversation is duplex: the reply is spoken the moment it lands).
  naturalPacing: () => boolean;
  // Seeds the tail from a stale-while-reconnecting hold, so a conversation renders immediately
  // across a controller epoch instead of blanking to a skeleton; seedTail refetches and merges by id.
  initialState?: ChatState;
}

export interface ChatSessionCallbacks {
  // A reply committed to the tail (after its typing delay, or at once), for speech and desktop
  // notifications. Fires exactly once per reply, in tail order.
  onReply?: (text: string) => void;
  // The next paced reply, announced when its typing delay starts, so speech can be prepared.
  onPrefetch?: (text: string) => void;
}

export interface ChatSessionState {
  chat: ChatState;
  typing: boolean;
  loadingMore: boolean;
  socket: ChatSocketState;
  // The newest reply committed live (not from history), for surfaces that react to arrivals.
  latestReply: string | null;
  // Bumped on every successful reseed, so a sibling surface can refetch its own history.
  reseedRevision: number;
}

export interface ChatSession {
  getState: () => ChatSessionState;
  subscribe: (listener: () => void) => () => void;
  send: (
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  retry: (
    intentId: string,
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  loadMore: () => Promise<void>;
  trimHistory: () => void;
  // Commit every paced reply at once; the caller's way to end a typing animation early.
  flushPacing: () => void;
  reportSpeaking: (speaking: boolean) => void;
  close: () => void;
}

// The chat view-model, framework-free: the replay-free app-chat socket joined to the HTTP history
// page by event id, the pacing queue that types replies out, and the send path confirmed by its
// echo. ChatState is the single source of truth; every fold runs synchronously against it so a
// batch of appends dedups against the running accumulation. The tail is seeded at creation, in
// parallel with the socket handshake (the fetch needs only the Bearer header), and reseeded on
// every later open so a gap self-heals; parked retry bubbles re-post on every open.
export function createChatSession(
  deps: ChatSessionDeps,
  callbacks: ChatSessionCallbacks = {},
): ChatSession {
  const fetchHistory =
    deps.fetchHistory ??
    ((cursor?: number) => fetchChatHistory(deps.http, deps.agent, cursor));

  let state: ChatSessionState = {
    chat: deps.initialState ?? initialChatState(),
    typing: false,
    loadingMore: false,
    socket: "connecting",
    latestReply: null,
    reseedRevision: 0,
  };
  const listeners = new Set<() => void>();
  const update = (patch: Partial<ChatSessionState>): void => {
    state = { ...state, ...patch };
    for (const listener of listeners) listener();
  };
  const commit = (fold: (current: ChatState) => ChatState): void => {
    update({ chat: fold(state.chat) });
  };

  let closed = false;
  let socketOpen = false;

  // The pacing queue: replies wait their typing delay one at a time; a burst past the threshold,
  // pacing off, or a flush commits everything at once.
  const queue: ChatMessage[] = [];
  let typingTimer: ReturnType<typeof setTimeout> | null = null;
  const clearTypingTimer = (): void => {
    if (typingTimer !== null) clearTimeout(typingTimer);
    typingTimer = null;
  };
  const commitReply = (event: ChatMessage): void => {
    const text = event.type === "chat" ? event.text : null;
    update({
      chat: commitPacedChat(state.chat, event),
      ...(text === null ? {} : { latestReply: text }),
    });
    if (text !== null) callbacks.onReply?.(text);
  };
  const flushQueue = (): void => {
    clearTypingTimer();
    const queued = queue.splice(0);
    for (const event of queued) commitReply(event);
    update({ typing: false });
  };
  const resetPacing = (): void => {
    clearTypingTimer();
    queue.length = 0;
    update({ typing: false });
  };
  const drainQueue = (): void => {
    if (typingTimer !== null) return;
    const next = queue[0];
    if (next === undefined) {
      if (state.typing) update({ typing: false });
      return;
    }
    if (queue.length > PACING.flushThreshold || !deps.naturalPacing()) {
      flushQueue();
      return;
    }
    update({ typing: true });
    const text = next.type === "chat" ? next.text : undefined;
    if (text !== undefined) callbacks.onPrefetch?.(text);
    typingTimer = setTimeout(
      () => {
        typingTimer = null;
        queue.shift();
        commitReply(next);
        drainQueue();
      },
      typingDelay(text?.length ?? 0),
    );
  };

  // Reseed the tail from the newest history page and MERGE, never replace: the model dedups by
  // id and reconciles pending sends against the page.
  let seedRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let seedRetryDelay = SEED_RETRY_BASE_MS;
  let mountSeedSucceeded = false;
  const clearSeedRetry = (): void => {
    if (seedRetryTimer !== null) clearTimeout(seedRetryTimer);
    seedRetryTimer = null;
  };
  const runSeed = (): void => {
    void fetchHistory().then(
      (page) => {
        if (closed) return;
        mountSeedSucceeded = true;
        seedRetryDelay = SEED_RETRY_BASE_MS;
        update({
          chat: seedTail(state.chat, page),
          reseedRevision: state.reseedRevision + 1,
        });
      },
      (error: unknown) => {
        console.warn("chat: history load failed", error);
        if (closed || !socketOpen) return;
        seedRetryTimer = setTimeout(() => {
          seedRetryTimer = null;
          runSeed();
        }, seedRetryDelay);
        seedRetryDelay = Math.min(seedRetryDelay * 2, SEED_RETRY_MAX_MS);
      },
    );
  };
  runSeed();

  const sender: ChatSender = createChatSender({
    http: deps.http,
    agent: deps.agent,
    commit,
    current: () => state.chat,
    makeId: deps.makeId,
  });

  let sawOpen = false;
  const socket = createChatSocket(
    { buildUrl: deps.buildUrl, createSocket: deps.createSocket },
    {
      onEvent: (event) => {
        const { state: next, paced } = foldLiveEvent(state.chat, event);
        update({ chat: next });
        if (paced) {
          queue.push(event);
          drainQueue();
        }
      },
      onStateChange: (socketState) => {
        socketOpen = socketState === "open";
        clearSeedRetry();
        update({ socket: socketState });
        if (!socketOpen) return;
        resetPacing();
        seedRetryDelay = SEED_RETRY_BASE_MS;
        // The first open skips the refetch the creation seed already landed; every later open
        // reseeds, and a first open racing a still-inflight seed reseeds too, so a seed that fails
        // after this check cannot strand the tail.
        if (sawOpen || !mountSeedSucceeded) runSeed();
        sawOpen = true;
        // Every open, including the first: a hold can carry parked retry bubbles across a remount,
        // and the re-post dedups on its original intent id.
        sender.repostParked();
      },
    },
  );

  let loadingMore = false;
  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    send: (text, inputMethod = "typed", attachments) => {
      sender.send(text, inputMethod, attachments);
    },
    retry: (intentId, text, inputMethod = "typed", attachments) => {
      sender.retry(intentId, text, inputMethod, attachments);
    },
    loadMore: async () => {
      const cursor = state.chat.cursor;
      if (loadingMore || cursor === null) return;
      loadingMore = true;
      update({ loadingMore: true });
      try {
        const page = await fetchHistory(cursor);
        if (closed) return;
        commit((current) => prependPage(current, page.events, page.cursor));
      } catch (error) {
        // hasMore stays truthy, so the next scroll to the top retries the page naturally.
        console.warn("chat: history page load failed", error);
      } finally {
        loadingMore = false;
        if (!closed) update({ loadingMore: false });
      }
    },
    // Skipped while a load is in flight: trimming under an unresolved prepend would leave a hole
    // between the landed page and the kept tail.
    trimHistory: () => {
      if (loadingMore) return;
      commit((current) => trimTail(current));
    },
    flushPacing: flushQueue,
    reportSpeaking: socket.reportSpeaking,
    close: () => {
      closed = true;
      clearSeedRetry();
      resetPacing();
      socket.close();
    },
  };
}
