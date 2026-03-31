import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";
import { createBoxConnection } from "./ws";

let channelCallback: ((event: any) => void) | null = null;
let invokeImpl: (...args: any[]) => Promise<any>;

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn((...args: any[]) => invokeImpl(...args)),
  Channel: vi.fn().mockImplementation(function (this: any) {
    Object.defineProperty(this, "onmessage", {
      set(fn: any) {
        channelCallback = fn;
      },
      get() {
        return channelCallback;
      },
    });
  }),
}));

function simulateOpen() {
  channelCallback?.({ kind: "Open" });
}

function simulateMessage(data: any) {
  channelCallback?.({ kind: "Message", text: JSON.stringify(data) });
}

function simulateClose() {
  channelCallback?.({ kind: "Close" });
}

beforeEach(() => {
  channelCallback = null;
  invokeImpl = vi.fn().mockResolvedValue(undefined);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createBoxConnection", () => {
  it("calls connect_ws on connect", async () => {
    const conn = createBoxConnection("test-agent");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    const { invoke } = await import("@tauri-apps/api/core");
    expect(invoke).toHaveBeenCalledWith("connect_ws", expect.objectContaining({ name: "test-agent" }));
    conn.disconnect();
  });

  it("sets connected to true on open", async () => {
    const conn = createBoxConnection("agent1");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    expect(get(conn.connected)).toBe(true);
    conn.disconnect();
  });

  it("sets connected to false on disconnect", async () => {
    const conn = createBoxConnection("agent2");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    conn.disconnect();
    expect(get(conn.connected)).toBe(false);
  });

  it("send returns false when not connected", () => {
    const conn = createBoxConnection("agent3");
    expect(conn.send("hello")).toBe(false);
  });

  it("send returns true and sends via invoke when connected", async () => {
    const conn = createBoxConnection("agent4");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    expect(conn.send("hello")).toBe(true);
    const { invoke } = await import("@tauri-apps/api/core");
    expect(invoke).toHaveBeenCalledWith("send_ws", {
      name: "agent4",
      text: JSON.stringify({ type: "message", text: "hello" }),
    });
    conn.disconnect();
  });

  it("handles history events", async () => {
    const conn = createBoxConnection("agent5");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    simulateMessage({
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
    simulateOpen();
    simulateMessage({ type: "status", state: "thinking" });
    expect(get(conn.boxState)).toBe("thinking");
    conn.disconnect();
  });

  it("does not reconnect after disconnect", async () => {
    const { invoke } = await import("@tauri-apps/api/core");
    const callsBefore = (invoke as any).mock.calls.filter((c: any) => c[0] === "connect_ws").length;
    const conn = createBoxConnection("agent7");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    conn.disconnect();
    simulateClose();
    await vi.advanceTimersByTimeAsync(60000);
    const callsAfter = (invoke as any).mock.calls.filter((c: any) => c[0] === "connect_ws").length;
    expect(callsAfter - callsBefore).toBe(1);
  });

  it("reconnects on unexpected close", async () => {
    const conn = createBoxConnection("agent8");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    simulateClose();
    await vi.advanceTimersByTimeAsync(1500);
    const { invoke } = await import("@tauri-apps/api/core");
    const connectCalls = (invoke as any).mock.calls.filter((c: any) => c[0] === "connect_ws");
    expect(connectCalls.length).toBeGreaterThan(1);
    conn.disconnect();
  });

  it("resetReconnect triggers immediate reconnect", async () => {
    const conn = createBoxConnection("agent9");
    conn.connect();
    await vi.advanceTimersByTimeAsync(0);
    simulateOpen();
    simulateClose();
    conn.resetReconnect();
    await vi.advanceTimersByTimeAsync(0);
    const { invoke } = await import("@tauri-apps/api/core");
    const connectCalls = (invoke as any).mock.calls.filter((c: any) => c[0] === "connect_ws");
    expect(connectCalls.length).toBeGreaterThan(1);
    conn.disconnect();
  });
});
