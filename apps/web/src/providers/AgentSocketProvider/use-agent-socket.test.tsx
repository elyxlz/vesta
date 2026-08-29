import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ApiError } from "@vesta/core";
import type { Controller, SocketLike, Tree, VestaEvent } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useChatPacing } from "@/stores/use-chat-pacing";
import { fetchHistory } from "@/api/agents";
import { fakeController, fakeTree } from "@/test/fake-controller";
import { useAgentSocketState } from "./use-agent-socket";

vi.mock("@/api/agents", () => ({ fetchHistory: vi.fn() }));
// The socket dials with the refreshed access token in the query; a fresh value per build lets the
// mount case pin that the token reaches the URL. Re-derivation on reconnect is covered at the owner
// (chat-socket.test.ts).
let tokenBuilds = 0;
vi.mock("@/lib/authed-url", () => ({
  websocketUrl: (path: string) => {
    tokenBuilds += 1;
    return Promise.resolve(
      `wss://vestad.test${path}?token=access-${String(tokenBuilds)}`,
    );
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
  return fakeTree({
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
  });
}

function makeController() {
  return fakeController(tree());
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
  tokenBuilds = 0;
  fetchHistoryMock.mockReset();
  useChatPacing.setState({ natural: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useAgentSocketState", () => {
  it("opens a chat socket and hydrates the newest history page", async () => {
    fetchHistoryMock.mockResolvedValue({
      events: [chat(1, "hello")],
      cursor: null,
    });
    const { controller } = makeController();

    const { result } = render(controller);
    await openAndFlush();
    expect(chatSockets).toHaveLength(1);
    expect(chatSockets[0]?.url).toBe(
      "wss://vestad.test/agents/ada/app-chat/ws?token=access-1",
    );

    expect(fetchHistoryMock).toHaveBeenCalledWith(AGENT, "app-chat");
    expect(result.current.historyLoaded).toBe(true);
    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.connected).toBe(true);
  });

  // The history fetch needs only the Bearer header, so it runs in parallel with the socket
  // handshake instead of waiting for "open": the tail renders after one round trip.
  it("seeds history at mount without waiting for the socket to open", async () => {
    fetchHistoryMock.mockResolvedValue({
      events: [chat(1, "hello")],
      cursor: null,
    });
    const { controller } = makeController();

    const { result } = render(controller);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.historyLoaded).toBe(true);
    expect(chatSockets.at(-1)?.onopen).not.toBeNull();
  });

  it("does not refetch on the first open after the mount seed landed", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller } = makeController();

    render(controller);
    await openAndFlush();

    expect(fetchHistoryMock).toHaveBeenCalledTimes(1);
  });

  it("reseeds on the first open when the mount seed failed", async () => {
    fetchHistoryMock
      .mockRejectedValueOnce(new Error("gateway hiccup"))
      .mockResolvedValueOnce({ events: [chat(1, "hello")], cursor: null });
    const { controller } = makeController();

    const { result } = render(controller);
    await openAndFlush();

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.historyLoaded).toBe(true);
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
