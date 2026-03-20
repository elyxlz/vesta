import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";
import { createBoxConnection } from "./ws";

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: any) => void) | null = null;
  onclose: ((ev: any) => void) | null = null;
  onmessage: ((ev: any) => void) | null = null;
  onerror: ((ev: any) => void) | null = null;
  url: string;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({});
  }

  simulateMessage(data: any) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }
}

let instances: MockWebSocket[] = [];

vi.stubGlobal("WebSocket", MockWebSocket);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue({
    url: "https://localhost:7860",
    api_key: "test-key",
    cert_fingerprint: "",
  }),
}));

beforeEach(() => {
  instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createBoxConnection", () => {
  it("creates connection with correct URL", async () => {
    const conn = createBoxConnection("test-agent");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    expect(instances).toHaveLength(1);
    expect(instances[0].url).toBe("wss://localhost:7860/agents/test-agent/ws?token=test-key");
    conn.disconnect();
  });

  it("sets connected to true on open", async () => {
    const conn = createBoxConnection("agent1");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    expect(get(conn.connected)).toBe(true);
    conn.disconnect();
  });

  it("sets connected to false on disconnect", async () => {
    const conn = createBoxConnection("agent2");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    conn.disconnect();
    expect(get(conn.connected)).toBe(false);
  });

  it("send returns false when not connected", () => {
    const conn = createBoxConnection("agent3");
    expect(conn.send("hello")).toBe(false);
  });

  it("send returns true and sends JSON when connected", async () => {
    const conn = createBoxConnection("agent4");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    expect(conn.send("hello")).toBe(true);
    expect(instances[0].sent).toHaveLength(1);
    expect(JSON.parse(instances[0].sent[0])).toEqual({ type: "message", text: "hello" });
    conn.disconnect();
  });

  it("handles history events", async () => {
    const conn = createBoxConnection("agent5");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    instances[0].simulateMessage({
      type: "history",
      events: [
        { type: "user", text: "hi" },
        { type: "assistant", text: "hello" },
      ],
      state: "idle",
    });
    const msgs = get(conn.messages);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toEqual({ type: "user", text: "hi" });
    conn.disconnect();
  });

  it("updates boxState on status event", async () => {
    const conn = createBoxConnection("agent6");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    instances[0].simulateMessage({ type: "status", state: "thinking" });
    expect(get(conn.boxState)).toBe("thinking");
    conn.disconnect();
  });

  it("does not reconnect after disconnect", async () => {
    const conn = createBoxConnection("agent7");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    conn.disconnect();
    await vi.advanceTimersByTimeAsync(60000);
    expect(instances).toHaveLength(1);
  });

  it("reconnects on unexpected close", async () => {
    const conn = createBoxConnection("agent8");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    const first = instances[0];
    first.simulateOpen();
    first.simulateClose();
    await vi.advanceTimersByTimeAsync(1500);
    expect(instances.length).toBeGreaterThan(1);
    conn.disconnect();
  });

  it("resetReconnect triggers immediate reconnect", async () => {
    const conn = createBoxConnection("agent9");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    instances[0].simulateOpen();
    instances[0].simulateClose();
    conn.resetReconnect();
    await vi.advanceTimersByTimeAsync(0);
    expect(instances.length).toBeGreaterThan(1);
    conn.disconnect();
  });
});
