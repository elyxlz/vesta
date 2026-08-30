import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { ApiError, PACING } from "@vesta/core";
import type { Controller, SocketLike, VestaEvent } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useChatPacing } from "@/stores/use-chat-pacing";
import { useVoice } from "@/stores/use-voice";
import { fetchHistory } from "@/api/agents";
import {
  fakeAgentNode,
  fakeController,
  fakeTree,
} from "@/test/fake-controller";
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

// The longest typing delay pacing can produce, so a paced message is guaranteed to have landed
// after it whatever the randomised jitter chose.
const MAX_TYPING_DELAY_MS = PACING.max * (1 + PACING.variance);

function makeController() {
  return fakeController(
    fakeTree({ agents: { ada: fakeAgentNode(), grace: fakeAgentNode() } }),
  );
}

function wrapper(controller: Controller) {
  return ({ children }: { children: ReactNode }) =>
    createElement(ControllerContext.Provider, { value: controller }, children);
}

interface HookProps {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
}

function render(controller: Controller, initial: Partial<HookProps> = {}) {
  return renderHook((props: HookProps) => useAgentSocketState(props), {
    wrapper: wrapper(controller),
    initialProps: { name: AGENT, active: true, ...initial },
  });
}

// Drain every pending microtask (the async URL build, the history seed, a settled POST), under real
// or fake timers alike, without counting awaits.
async function settle() {
  await act(async () => {
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(0);
    else await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

// Open the newest chat socket (the reseed trigger) and let the hook settle.
async function openAndFlush() {
  await settle();
  const socket = chatSockets.at(-1);
  if (!socket?.onopen) throw new Error("chat socket not constructed");
  act(() => {
    socket.onopen?.();
  });
  await settle();
}

// Deliver one live event on the chat socket, as a JSON text frame.
function deliver(event: VestaEvent): void {
  act(() => {
    chatSockets.at(-1)?.onmessage?.(JSON.stringify(event));
  });
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

function postedIntentId(
  json: ReturnType<typeof makeController>["json"],
  call = 0,
): string {
  const args = json.mock.calls[call];
  if (!args) throw new Error("send did not POST");
  const body = JSON.parse((args[1] as { body: string }).body) as {
    intent_id: string;
  };
  return body.intent_id;
}

beforeEach(() => {
  chatSockets.length = 0;
  tokenBuilds = 0;
  fetchHistoryMock.mockReset();
  fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
  useChatPacing.setState({ byAgent: {} });
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

  it("opens no socket and fetches nothing while inactive", async () => {
    const { controller } = makeController();

    render(controller, { active: false });
    await settle();

    expect(chatSockets).toHaveLength(0);
    expect(fetchHistoryMock).not.toHaveBeenCalled();
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

    await waitFor(() => {
      expect(result.current.historyLoaded).toBe(true);
    });
    expect(chatSockets.at(-1)?.onopen).not.toBeNull();
  });

  it("does not refetch on the first open after the mount seed landed", async () => {
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

  // Switching the viewed agent is a fresh session: the old socket closes, the rows reset, and the new
  // agent's tail is fetched and dialled.
  it("resets and re-dials when the agent changes", async () => {
    fetchHistoryMock.mockResolvedValue({
      events: [chat(1, "hello")],
      cursor: null,
    });
    const { controller } = makeController();
    const { result, rerender } = render(controller);
    await openAndFlush();
    expect(result.current.messages).toHaveLength(1);

    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    rerender({ name: "grace", active: true });

    expect(chatSockets[0]?.closed).toBe(true);
    expect(result.current.messages).toHaveLength(0);
    await openAndFlush();
    expect(chatSockets).toHaveLength(2);
    expect(chatSockets[1]?.url).toContain("/agents/grace/app-chat/ws");
    expect(fetchHistoryMock).toHaveBeenLastCalledWith("grace", "app-chat");
  });

  it("sends an optimistic bubble and confirms it on the chat-socket echo", async () => {
    const { controller, json } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      expect(result.current.send("hi")).toBe(true);
    });
    await settle();

    // Delivery truth is the echo, so the bubble is optimistic ("sending") until it returns.
    const users = () =>
      result.current.messages.filter((m) => m.type === "user");
    expect(users()).toHaveLength(1);
    expect(users()[0]).toMatchObject({ text: "hi", send_state: "sending" });

    deliver(userEcho(5, "hi", postedIntentId(json)));

    // The echo confirms the existing bubble rather than appending a second.
    expect(users()).toHaveLength(1);
    expect(users()[0]?.send_state).toBeUndefined();
  });

  it("keeps the bubble and marks it retry when the send POST returns 503", async () => {
    const { controller, json } = makeController();
    json.mockRejectedValueOnce(new ApiError(503, "unavailable"));
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      expect(result.current.send("retryable")).toBe(true);
    });
    await settle();

    const users = result.current.messages.filter((m) => m.type === "user");
    expect(users).toHaveLength(1);
    expect(users[0]).toMatchObject({ text: "retryable", send_state: "retry" });
  });

  // A retry re-posts under the ORIGINAL intent id, so the agent dedups it instead of receiving the
  // message twice; the bubble goes back to sending and the same echo confirms it.
  it("retries a failed send under its original intent id and confirms on the echo", async () => {
    const { controller, json } = makeController();
    json.mockRejectedValueOnce(new ApiError(503, "unavailable"));
    const { result } = render(controller);
    await openAndFlush();
    act(() => {
      result.current.send("again");
    });
    await settle();
    const intentId = postedIntentId(json);
    const users = () =>
      result.current.messages.filter((m) => m.type === "user");

    act(() => {
      result.current.retry(intentId, "again");
    });
    expect(users()[0]).toMatchObject({ send_state: "sending" });
    await settle();

    expect(json).toHaveBeenCalledTimes(2);
    expect(postedIntentId(json, 1)).toBe(intentId);
    deliver(userEcho(9, "again", intentId));
    expect(users()).toHaveLength(1);
    expect(users()[0]?.send_state).toBeUndefined();
  });

  // Older history pages prepend above the tail and advance the cursor; trimming waits out an
  // in-flight load so it never cuts a hole between the landing page and the kept tail.
  it("prepends older history on loadMore and defers trimming while a load is in flight", async () => {
    const seeded = Array.from({ length: 120 }, (_, i) =>
      chat(100 + i, `m${String(i)}`),
    );
    fetchHistoryMock.mockResolvedValue({ events: seeded, cursor: 100 });
    const { controller } = makeController();
    const { result } = render(controller);
    await openAndFlush();
    expect(result.current.hasMore).toBe(true);

    let resolveOlder: (page: {
      events: VestaEvent[];
      cursor: null;
    }) => void = () => undefined;
    fetchHistoryMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOlder = resolve;
      }),
    );
    let load: Promise<void> = Promise.resolve();
    act(() => {
      load = result.current.loadMore();
    });
    expect(fetchHistoryMock).toHaveBeenLastCalledWith(AGENT, "app-chat", 100);
    expect(result.current.loadingMore).toBe(true);

    act(() => {
      result.current.trimHistory();
    });
    expect(result.current.messages).toHaveLength(120);

    await act(async () => {
      resolveOlder({ events: [chat(50, "old")], cursor: null });
      await load;
    });
    expect(result.current.messages[0]).toMatchObject({ id: 50, text: "old" });
    expect(result.current.messages).toHaveLength(121);
    expect(result.current.hasMore).toBe(false);
    expect(result.current.loadingMore).toBe(false);

    act(() => {
      result.current.trimHistory();
    });
    expect(result.current.messages.length).toBeLessThan(121);
    expect(result.current.hasMore).toBe(true);
  });

  it("paces a live chat event, toggling isTyping and firing onAssistantMessage on commit", async () => {
    vi.useFakeTimers();
    const onAssistantMessage = vi.fn();
    const { controller } = makeController();
    const { result } = render(controller, { onAssistantMessage });
    await openAndFlush();

    deliver(chat(7, "pong"));

    // Paced: typing indicator on, message withheld until the typing delay elapses.
    expect(result.current.isTyping).toBe(true);
    expect(result.current.messages).toHaveLength(0);
    expect(onAssistantMessage).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MAX_TYPING_DELAY_MS);
    });

    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.isTyping).toBe(false);
    expect(onAssistantMessage).toHaveBeenCalledWith("pong");
  });

  // Pacing is a feel, not a contract: with natural pacing off every event commits at once, and a
  // burst past the flush threshold is dumped after the first delay rather than typed out one by one.
  it("commits at once with natural pacing off", async () => {
    useChatPacing.setState({ byAgent: { [AGENT]: false } });
    const { controller } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    deliver(chat(7, "pong"));

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.isTyping).toBe(false);
  });

  it("commits at once during a voice conversation", async () => {
    useVoice.setState({ recordingMode: "conversation" });
    try {
      const onAssistantMessage = vi.fn();
      const { controller } = makeController();
      const { result } = render(controller, { onAssistantMessage });
      await openAndFlush();

      deliver(chat(7, "pong"));

      expect(result.current.messages).toHaveLength(1);
      expect(onAssistantMessage).toHaveBeenCalledWith("pong");
    } finally {
      useVoice.setState({ recordingMode: null });
    }
  });

  it("flushes a burst past the threshold after one typing delay", async () => {
    vi.useFakeTimers();
    const { controller } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    const burst = PACING.flushThreshold + 2;
    for (let i = 0; i < burst; i++) deliver(chat(10 + i, `m${String(i)}`));
    expect(result.current.messages).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MAX_TYPING_DELAY_MS);
    });

    expect(result.current.messages).toHaveLength(burst);
    expect(result.current.isTyping).toBe(false);
  });
});

describe("attachments on the send path", () => {
  const ATTACHMENT = {
    id: "att1",
    name: "photo.jpg",
    mime: "image/jpeg",
    size: 9,
  };

  it("posts finalized ids and carries metadata on the optimistic bubble", async () => {
    const { controller, json } = makeController();
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      expect(result.current.send("look", "typed", [ATTACHMENT])).toBe(true);
    });
    await settle();

    const call = json.mock.calls[0];
    if (!call) throw new Error("send did not POST");
    const body = JSON.parse((call[1] as { body: string }).body) as Record<
      string,
      unknown
    >;
    expect(body.attachments).toEqual(["att1"]);
    const users = result.current.messages.filter((m) => m.type === "user");
    expect(users[0]).toMatchObject({
      attachments: [ATTACHMENT],
      send_state: "sending",
    });
  });

  it("re-posts a retry-state bubble under its original id on reconnect", async () => {
    const { controller, json } = makeController();
    json.mockRejectedValueOnce(new ApiError(503, "unavailable"));
    const { result } = render(controller);
    await openAndFlush();

    act(() => {
      result.current.send("stuck", "typed", [ATTACHMENT]);
    });
    await settle();
    const users = () =>
      result.current.messages.filter((m) => m.type === "user");
    expect(users()[0]).toMatchObject({ send_state: "retry" });
    const intentId = postedIntentId(json);

    // The socket re-opens (a reconnect edge): the parked bubble re-posts itself once.
    act(() => {
      chatSockets.at(-1)?.onopen?.();
    });
    await settle();

    expect(json).toHaveBeenCalledTimes(2);
    expect(postedIntentId(json, 1)).toBe(intentId);
    const replay = json.mock.calls[1];
    if (!replay) throw new Error("no re-post");
    const replayBody = JSON.parse(
      (replay[1] as { body: string }).body,
    ) as Record<string, unknown>;
    expect(replayBody.attachments).toEqual(["att1"]);
    expect(users()[0]).toMatchObject({ send_state: "sending" });
  });

  it("does not re-post on the very first open", async () => {
    const { controller, json } = makeController();
    const { result } = render(controller);
    await openAndFlush();
    act(() => {
      expect(result.current.send("hello")).toBe(true);
    });
    await settle();
    expect(json).toHaveBeenCalledTimes(1);
  });
});
