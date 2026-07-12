import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectReconnectingWs } from "./reconnecting-ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("connectReconnectingWs", () => {
  it("opens a socket and forwards text frames only", () => {
    const messages: string[] = [];
    connectReconnectingWs({
      url: () => "ws://host/a",
      onMessage: (data) => messages.push(data),
    });
    expect(FakeSocket.instances).toHaveLength(1);
    const socket = FakeSocket.instances[0];
    socket.open();
    socket.emit("hello");
    socket.emit(new ArrayBuffer(4));
    socket.emit("world");
    expect(messages).toEqual(["hello", "world"]);
  });

  it("reconnects on close with exponential backoff that resets on open", () => {
    connectReconnectingWs({
      url: () => "ws://host/a",
      onMessage: () => {},
      baseDelayMs: 1000,
      maxDelayMs: 30000,
    });
    FakeSocket.instances[0].drop();
    // first retry after the base delay
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    // second consecutive drop doubles the delay to 2000ms
    FakeSocket.instances[1].drop();
    vi.advanceTimersByTime(1999);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(3);
    // a successful open resets the backoff to the base delay again
    FakeSocket.instances[2].open();
    FakeSocket.instances[2].drop();
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances).toHaveLength(4);
  });

  it("retries when the url builder throws, without creating a socket", () => {
    let ready = false;
    connectReconnectingWs({
      url: () => {
        if (!ready) throw new Error("not ready");
        return "ws://host/a";
      },
      onMessage: () => {},
      baseDelayMs: 1000,
    });
    expect(FakeSocket.instances).toHaveLength(0);
    ready = true;
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("runs beforeConnect and stops the loop without opening on a stop verdict", async () => {
    let proceed = false;
    const handle = connectReconnectingWs({
      beforeConnect: () => Promise.resolve(proceed ? "open" : "stop"),
      url: () => "ws://host/a",
      onMessage: () => {},
    });
    await vi.runAllTimersAsync();
    expect(FakeSocket.instances).toHaveLength(0);
    expect(handle.current()).toBeNull();
    // a stop verdict cancels the loop: a later turn never reconnects
    proceed = true;
    await vi.runAllTimersAsync();
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("opens after beforeConnect resolves open", async () => {
    connectReconnectingWs({
      beforeConnect: () => Promise.resolve("open"),
      url: () => "ws://host/a",
      onMessage: () => {},
    });
    await vi.runAllTimersAsync();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("close() tears down the socket and stops the reconnect loop", () => {
    const handle = connectReconnectingWs({
      url: () => "ws://host/a",
      onMessage: () => {},
    });
    const socket = FakeSocket.instances[0];
    handle.close();
    expect(socket.closed).toBe(true);
    expect(socket.onclose).toBeNull();
    expect(handle.current()).toBeNull();
    // a late close after teardown must not schedule a reconnect
    vi.advanceTimersByTime(60000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
