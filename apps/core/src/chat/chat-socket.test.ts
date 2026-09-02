import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createChatSocket } from "./chat-socket";
import type { ChatSocketState } from "./chat-socket";
import type { ChatMessage } from "./chat-stream-model";
import type { SocketLike } from "../transport/websocket";

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  sent: string[] = [];
  send(data: string | ArrayBuffer): void {
    this.sent.push(typeof data === "string" ? data : "<binary>");
  }
  close(): void {
    this.closed = true;
  }
}

interface Harness {
  sockets: FakeSocket[];
  urls: string[];
  states: ChatSocketState[];
  events: ChatMessage[];
  deps: Parameters<typeof createChatSocket>[0];
}

function harness(): Harness {
  const sockets: FakeSocket[] = [];
  const urls: string[] = [];
  const states: ChatSocketState[] = [];
  const events: ChatMessage[] = [];
  let builds = 0;
  const deps = {
    // A fresh credential per attempt, as the real builder refreshes the token: the counter makes
    // it observable that the URL is re-derived rather than captured once.
    buildUrl: () => {
      builds += 1;
      return Promise.resolve(
        `wss://vestad.test/agents/ada/app-chat/ws?token=key-${String(builds)}`,
      );
    },
    createSocket: (url: string) => {
      urls.push(url);
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  };
  return { sockets, urls, states, events, deps };
}

// The URL builder is async, so the socket is created a microtask after createChatSocket returns.
const flush = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(0);
};
// The first reconnect fires after the base delay; the next socket is then dialed.
const reconnect = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(1000);
};

async function start(h: Harness): Promise<ReturnType<typeof createChatSocket>> {
  const socket = createChatSocket(h.deps, {
    onEvent: (event) => h.events.push(event),
    onStateChange: (state) => h.states.push(state),
  });
  await flush();
  return socket;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createChatSocket", () => {
  it("reports connecting then open", async () => {
    const h = harness();
    await start(h);
    expect(h.states).toEqual(["connecting"]);
    h.sockets[0]?.onopen?.();
    expect(h.states).toEqual(["connecting", "open"]);
  });

  it("delivers each inbound JSON frame as a parsed ChatMessage", async () => {
    const h = harness();
    await start(h);
    h.sockets[0]?.onopen?.();
    h.sockets[0]?.onmessage?.(
      JSON.stringify({ type: "chat", text: "hi", id: 7 }),
    );
    expect(h.events).toEqual([{ type: "chat", text: "hi", id: 7 }]);
  });

  it("ignores malformed JSON and frames the parser cannot classify", async () => {
    const h = harness();
    await start(h);
    h.sockets[0]?.onopen?.();
    h.sockets[0]?.onmessage?.("not json");
    h.sockets[0]?.onmessage?.(JSON.stringify({ type: "chat", id: 8 }));
    expect(h.events).toEqual([]);
  });

  it("reconnects after a close and re-signals open (the reseed trigger)", async () => {
    const h = harness();
    await start(h);
    h.sockets[0]?.onopen?.();
    h.sockets[0]?.onclose?.();
    expect(h.states).toEqual(["connecting", "open", "reconnecting"]);
    expect(vi.getTimerCount()).toBe(1);
    await reconnect();
    h.sockets[1]?.onopen?.();
    expect(h.states).toEqual([
      "connecting",
      "open",
      "reconnecting",
      "connecting",
      "open",
    ]);
  });

  it("does not reconnect after close() is terminal", async () => {
    const h = harness();
    const socket = await start(h);
    h.sockets[0]?.onopen?.();
    socket.close();
    expect(h.states.at(-1)).toBe("closed");
    expect(h.sockets[0]?.closed).toBe(true);
    h.sockets[0]?.onclose?.();
    expect(vi.getTimerCount()).toBe(0);
  });

  // The credential rides in the URL, so a reconnect hours after mount must re-derive it. Capturing
  // one URL at construction would dial the reconnect with a key that expired in the meantime.
  it("re-derives the url on every reconnect", async () => {
    const h = harness();
    await start(h);
    h.sockets[0]?.onopen?.();
    h.sockets[0]?.onclose?.();
    await reconnect();

    expect(h.urls).toEqual([
      "wss://vestad.test/agents/ada/app-chat/ws?token=key-1",
      "wss://vestad.test/agents/ada/app-chat/ws?token=key-2",
    ]);
  });

  it("keeps reconnecting through a streak of pre-open closes", async () => {
    const h = harness();
    await start(h);
    h.sockets[0]?.onclose?.();
    await reconnect();
    h.sockets[1]?.onclose?.();
    await vi.advanceTimersByTimeAsync(2000);

    expect(h.sockets).toHaveLength(3);
    expect(h.states).toEqual([
      "connecting",
      "reconnecting",
      "connecting",
      "reconnecting",
      "connecting",
    ]);
  });

  it("sends a speaking frame while open and dedups repeats", async () => {
    const h = harness();
    const socket = await start(h);
    h.sockets[0]?.onopen?.();
    socket.reportSpeaking(true);
    socket.reportSpeaking(true);
    socket.reportSpeaking(false);
    expect(h.sockets[0]?.sent).toEqual([
      JSON.stringify({ type: "speaking", active: true }),
      JSON.stringify({ type: "speaking", active: false }),
    ]);
  });

  it("drops a speaking report with no open socket and replays a live turn on reconnect", async () => {
    const h = harness();
    const socket = await start(h);
    h.sockets[0]?.onopen?.();
    h.sockets[0]?.onclose?.();
    socket.reportSpeaking(true);
    expect(h.sockets[0]?.sent).toEqual([]);
    await reconnect();
    h.sockets[1]?.onopen?.();
    expect(h.sockets[1]?.sent).toEqual([
      JSON.stringify({ type: "speaking", active: true }),
    ]);
  });

  it("replays nothing on reconnect once the turn ended", async () => {
    const h = harness();
    const socket = await start(h);
    h.sockets[0]?.onopen?.();
    socket.reportSpeaking(true);
    socket.reportSpeaking(false);
    h.sockets[0]?.onclose?.();
    await reconnect();
    h.sockets[1]?.onopen?.();
    expect(h.sockets[1]?.sent).toEqual([]);
  });

  it("schedules a reconnect when the url builder rejects", async () => {
    const h = harness();
    h.deps.buildUrl = () => Promise.reject(new Error("not connected"));
    await start(h);
    expect(h.states).toEqual(["connecting", "reconnecting"]);
    expect(h.sockets).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(1);
  });
});
