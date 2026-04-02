import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";

vi.mock("./connection", () => ({
  wsUrl: vi.fn((name: string) => `ws://localhost:7860/agents/${name}/ws?token=test`),
  getConnection: vi.fn(() => ({ url: "http://localhost:7860", apiKey: "test" })),
}));

let mockWs: any;
let mockWsInstances: any[] = [];

class MockWebSocket {
  url: string;
  readyState = 0;
  onopen: ((e: any) => void) | null = null;
  onmessage: ((e: any) => void) | null = null;
  onclose: ((e: any) => void) | null = null;
  onerror: ((e: any) => void) | null = null;

  static OPEN = 1;
  static CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    mockWs = this;
    mockWsInstances.push(this);
  }

  send = vi.fn();

  close() {
    this.readyState = 3;
    if (this.onclose) this.onclose({});
  }
}

(globalThis as any).WebSocket = MockWebSocket;

import { createAgentConnection } from "./ws";

beforeEach(() => {
  mockWs = null;
  mockWsInstances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createAgentConnection", () => {
  it("creates a WebSocket on connect", async () => {
    const conn = createAgentConnection("test-agent");
    conn.connect();
    expect(mockWs).not.toBeNull();
    expect(mockWs.url).toContain("test-agent");
    conn.disconnect();
  });

  it("sets connected to true on open", async () => {
    const conn = createAgentConnection("agent1");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    expect(get(conn.connected)).toBe(true);
    conn.disconnect();
  });

  it("sets connected to false on disconnect", async () => {
    const conn = createAgentConnection("agent2");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    conn.disconnect();
    expect(get(conn.connected)).toBe(false);
  });

  it("send returns false when not connected", () => {
    const conn = createAgentConnection("agent3");
    expect(conn.send("hello")).toBe(false);
  });

  it("send returns true and sends via WebSocket when connected", async () => {
    const conn = createAgentConnection("agent4");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    expect(conn.send("hello")).toBe(true);
    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "message", text: "hello" }),
    );
    conn.disconnect();
  });

  it("handles history events", async () => {
    const conn = createAgentConnection("agent5");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    mockWs.onmessage?.({
      data: JSON.stringify({
        type: "history",
        events: [
          { type: "user", text: "hi" },
          { type: "assistant", text: "hello" },
        ],
        state: "idle",
      }),
    });
    const msgs = get(conn.messages);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]).toEqual({ type: "user", text: "hi" });
    conn.disconnect();
  });

  it("updates agentState on status event", async () => {
    const conn = createAgentConnection("agent6");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    mockWs.onmessage?.({
      data: JSON.stringify({ type: "status", state: "thinking" }),
    });
    expect(get(conn.agentState)).toBe("thinking");
    conn.disconnect();
  });

  it("does not reconnect after disconnect", async () => {
    const conn = createAgentConnection("agent7");
    conn.connect();
    const initial = mockWsInstances.length;
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    conn.disconnect();
    await vi.advanceTimersByTimeAsync(60000);
    expect(mockWsInstances.length).toBe(initial);
  });

  it("reconnects on unexpected close", async () => {
    const conn = createAgentConnection("agent8");
    conn.connect();
    const initial = mockWsInstances.length;
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    mockWs.onclose?.({});
    await vi.advanceTimersByTimeAsync(1500);
    expect(mockWsInstances.length).toBeGreaterThan(initial);
    conn.disconnect();
  });

  it("resetReconnect triggers immediate reconnect", async () => {
    const conn = createAgentConnection("agent9");
    conn.connect();
    mockWs.readyState = 1;
    mockWs.onopen?.({});
    mockWs.onclose?.({});
    const beforeReset = mockWsInstances.length;
    conn.resetReconnect();
    expect(mockWsInstances.length).toBeGreaterThan(beforeReset);
    conn.disconnect();
  });
});
