import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRnSocket } from "./rn-socket";

class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn<(data: string) => void>();
  close = vi.fn<() => void>();

  constructor(readonly url: string) {
    FakeWebSocket.last = this;
  }

  emitOpen() {
    this.onopen?.();
  }
  emitMessage(data: unknown) {
    this.onmessage?.({ data });
  }
  emitClose() {
    this.onclose?.();
  }
}

function lastSocket(): FakeWebSocket {
  const socket = FakeWebSocket.last;
  if (!socket) throw new Error("createRnSocket did not construct a WebSocket");
  return socket;
}

beforeEach(() => {
  FakeWebSocket.last = null;
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => vi.unstubAllGlobals());

describe("createRnSocket", () => {
  it("forwards open to the adapter", () => {
    const adapter = createRnSocket("wss://gateway.example/sync");
    const onopen = vi.fn();
    adapter.onopen = onopen;

    lastSocket().emitOpen();

    expect(onopen).toHaveBeenCalledOnce();
  });

  it("forwards only string messages to the adapter", () => {
    const adapter = createRnSocket("wss://gateway.example/sync");
    const onmessage = vi.fn();
    adapter.onmessage = onmessage;

    lastSocket().emitMessage("hello");
    lastSocket().emitMessage(new ArrayBuffer(4));

    expect(onmessage).toHaveBeenCalledExactlyOnceWith("hello");
  });

  it("forwards close to the adapter", () => {
    const adapter = createRnSocket("wss://gateway.example/sync");
    const onclose = vi.fn();
    adapter.onclose = onclose;

    lastSocket().emitClose();

    expect(onclose).toHaveBeenCalledOnce();
  });

  it("delegates send and close to the underlying WebSocket", () => {
    const adapter = createRnSocket("wss://gateway.example/sync");

    adapter.send("frame");
    adapter.close();

    expect(lastSocket().send).toHaveBeenCalledExactlyOnceWith("frame");
    expect(lastSocket().close).toHaveBeenCalledOnce();
  });
});
