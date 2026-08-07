import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ApiError, createReplica } from "@vesta/core";
import type {
  Controller,
  Delta,
  SocketLike,
  Tree,
  VestaEvent,
} from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useChatPacing } from "@/stores/use-chat-pacing";
import { fetchHistory } from "@/api/agents";
import { useAgentSocketState } from "./use-agent-socket";

vi.mock("@/api/agents", () => ({ fetchHistory: vi.fn() }));
vi.mock("@/lib/connection", () => ({
  getConnection: () => ({
    url: "https://vestad.test",
    accessToken: ACCESS_TOKEN,
  }),
}));
// Distinct from the minted key and from the "token=" param name, so the assertion that the URL
// carries no access token fails on a real regression rather than on a substring.
const ACCESS_TOKEN = "full-privilege-access-token";
// app-chat is a private service, so the socket's only credential is a key minted for it. The cache
// is the true edge; a fresh secret per mint makes it observable which one the URL carried.
let minted = 0;
const dropped: string[] = [];
vi.mock("@/lib/service-key-cache", () => ({
  serviceKeys: {
    get: (_agent: string, service: string) => {
      minted += 1;
      return Promise.resolve(`${service}-key-${String(minted)}`);
    },
    drop: (agent: string, service: string) => {
      dropped.push(`${agent}/${service}`);
    },
  },
}));

// A controllable chat socket: createChatSocket sets its handlers, and each test drives them. The
// factory records every instance so a test can open it, feed a frame, or assert its URL.
class FakeChatSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  readonly url: string;
  constructor(url: string) {
    this.url = url;
  }
  send(): void {
    // The chat socket is read-only.
  }
  close(): void {
    this.closed = true;
  }
}

const chatSockets: FakeChatSocket[] = [];
vi.mock("@/providers/ControllerProvider/browser-socket", () => ({
  createBrowserSocket: (url: string) => {
    const socket = new FakeChatSocket(url);
    chatSockets.push(socket);
    return socket;
  },
}));

const fetchHistoryMock = vi.mocked(fetchHistory);

const AGENT = "ada";

function tree(): Tree {
  return {
    gateway: {
      version: "0.0.0",
      channel: "stable",
      autoUpdate: true,
      port: 7777,
      lan: { exposed: false, url: null },
      tunnelUrl: null,
      updateAvailable: false,
      latestVersion: null,
      managed: false,
    },
    agents: {
      [AGENT]: {
        info: {
          status: "alive",
          activityState: "idle",
          buildPhase: null,
          operation: null,
          startedAt: null,
          services: {},
        },
        notifications: { pending: [] },
      },
    },
    devices: [],
  };
}

function makeController() {
  const replica = createReplica();
  replica.applySnapshot(tree());
  const listeners = new Set<(delta: Delta) => void>();
  const json = vi.fn().mockResolvedValue({});
  const controller: Controller = {
    replica,
    http: { request: vi.fn(), json },
    reauth: vi.fn(),
    subscribeDeltas: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    reportPresence: () => undefined,
    getAnyFocused: () => false,
    subscribeAnyFocused: () => () => undefined,
    close: () => undefined,
  };
  return { controller, json };
}

function wrapper(controller: Controller) {
  return ({ children }: { children: ReactNode }) =>
    createElement(ControllerContext.Provider, { value: controller }, children);
}

function render(controller: Controller) {
  return renderHook(() => useAgentSocketState({ name: AGENT, active: true }), {
    wrapper: wrapper(controller),
  });
}

// Open the newest chat socket (the reseed trigger) and flush the async history seed so the hook
// settles.
async function openAndFlush() {
  // The URL builder is async, so the socket lands a microtask after the hook renders.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => {
    chatSockets.at(-1)?.onopen?.();
    await Promise.resolve();
    await Promise.resolve();
  });
}

// Deliver one live event on the chat socket, as a JSON text frame.
function deliver(event: VestaEvent): void {
  chatSockets.at(-1)?.onmessage?.(JSON.stringify(event));
}

function chat(id: number, text: string): VestaEvent {
  return { type: "chat", text, id, ts: new Date().toISOString() };
}

// The chat-socket echo of a send: a wire `user` event carrying `intent_id` (core's event type does
// not model that client-only field, so assert past it as the runtime frame does).
function userEcho(id: number, text: string, intentId: string): VestaEvent {
  return {
    type: "user",
    text,
    id,
    intent_id: intentId,
  } as unknown as VestaEvent;
}

beforeEach(() => {
  chatSockets.length = 0;
  minted = 0;
  dropped.length = 0;
  fetchHistoryMock.mockReset();
  useChatPacing.setState({ natural: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useAgentSocketState", () => {
  it("opens a chat socket and hydrates the newest history page on open", async () => {
    fetchHistoryMock.mockResolvedValue({
      events: [chat(1, "hello")],
      cursor: null,
    });
    const { controller } = makeController();

    const { result } = render(controller);
    await openAndFlush();
    expect(chatSockets).toHaveLength(1);
    expect(chatSockets[0]?.url).not.toContain(ACCESS_TOKEN);
    expect(chatSockets[0]?.url).toBe(
      "wss://vestad.test/agents/ada/app-chat/ws?token=app-chat-key-1",
    );

    expect(fetchHistoryMock).toHaveBeenCalledWith(AGENT, "app-chat");
    expect(result.current.historyLoaded).toBe(true);
    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.connected).toBe(true);
  });

  it("keeps loaded older rows before the newest tail after a reconnect", async () => {
    vi.useFakeTimers();
    fetchHistoryMock
      .mockResolvedValueOnce({
        events: [chat(3, "c"), chat(4, "d")],
        cursor: 3,
      })
      .mockResolvedValueOnce({
        events: [chat(1, "a"), chat(2, "b")],
        cursor: null,
      })
      .mockResolvedValueOnce({
        events: [chat(3, "c"), chat(4, "d"), chat(5, "e")],
        cursor: 3,
      });
    const { controller } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    await act(async () => {
      await result.current.loadMore();
    });
    expect(result.current.messages.map((message) => message.id)).toEqual([
      1, 2, 3, 4,
    ]);

    act(() => {
      chatSockets[0]?.onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await openAndFlush();

    expect(result.current.messages.map((message) => message.id)).toEqual([
      1, 2, 3, 4, 5,
    ]);
    expect(result.current.messages.at(-1)?.id).toBe(5);
    expect(result.current.hasMore).toBe(false);
  });

  // Asked through the cache on every connect, never captured at mount: a key that aged out while
  // the app was away is re-minted here (the cache's own expiry rule is pinned in service-keys.test).
  it("asks the cache for the key again on a reconnect", async () => {
    vi.useFakeTimers();
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller } = makeController();
    render(controller);
    await openAndFlush();

    act(() => {
      chatSockets[0]?.onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await openAndFlush();

    expect(chatSockets.map((socket) => socket.url)).toEqual([
      "wss://vestad.test/agents/ada/app-chat/ws?token=app-chat-key-1",
      "wss://vestad.test/agents/ada/app-chat/ws?token=app-chat-key-2",
    ]);
  });

  // A key revoked or expired between mint and connect makes the gateway refuse the upgrade, which
  // arrives as a close with no open. Without dropping it the socket would present the same refused
  // key on every backoff forever.
  it("drops the cached key when the socket closes before opening", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller } = makeController();
    render(controller);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => {
      chatSockets[0]?.onclose?.();
    });

    expect(dropped).toEqual(["ada/app-chat"]);
  });

  it("keeps the cached key when a live socket closes", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller } = makeController();
    render(controller);
    await openAndFlush();

    act(() => {
      chatSockets[0]?.onclose?.();
    });

    expect(dropped).toEqual([]);
  });

  it("sends an optimistic bubble and confirms it on the chat-socket echo", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller, json } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      expect(result.current.send("hi")).toBe(true);
    });
    await act(async () => {
      await Promise.resolve();
    });

    // Delivery truth is the echo, so the bubble is optimistic ("sending") until it returns.
    const users = () =>
      result.current.messages.filter((m) => m.type === "user");
    expect(users()).toHaveLength(1);
    expect(users()[0]).toMatchObject({ text: "hi", send_state: "sending" });

    const call = json.mock.calls[0];
    if (!call) throw new Error("send did not POST");
    const body = JSON.parse((call[1] as { body: string }).body) as {
      intent_id: string;
    };

    act(() => {
      deliver(userEcho(5, "hi", body.intent_id));
    });

    // The echo confirms the existing bubble rather than appending a second.
    expect(users()).toHaveLength(1);
    expect(users()[0]?.send_state).toBeUndefined();
  });

  it("paces a live chat event and toggles isTyping", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    vi.useFakeTimers();
    const { controller } = makeController();
    const { result } = render(controller);
    await act(async () => {
      chatSockets.at(-1)?.onopen?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => {
      deliver(chat(7, "pong"));
    });

    // Paced: typing indicator on, message withheld until the typing delay elapses.
    expect(result.current.isTyping).toBe(true);
    expect(result.current.messages).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });

    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.isTyping).toBe(false);
  });

  it("keeps the bubble and marks it retry when the send POST returns 503", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller, json } = makeController();
    json.mockRejectedValueOnce(new ApiError(503, "unavailable"));
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      expect(result.current.send("retryable")).toBe(true);
    });
    await act(async () => {
      await Promise.resolve();
    });

    const users = result.current.messages.filter((m) => m.type === "user");
    expect(users).toHaveLength(1);
    expect(users[0]).toMatchObject({ text: "retryable", send_state: "retry" });
  });
});
