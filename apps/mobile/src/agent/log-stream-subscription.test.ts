import { afterEach, describe, expect, it, vi } from "vitest";
import type { SseHandle, StreamEvent } from "@vesta/core";
import { subscribeLogs, type LogStream } from "./log-stream-subscription";

interface FakeStream {
  reconnect: boolean;
  emit: (event: StreamEvent) => void;
  cancel: ReturnType<typeof vi.fn>;
}

afterEach(() => {
  vi.useRealTimers();
});

function makeHarness(overrides?: Partial<LogStream>) {
  const streams: FakeStream[] = [];
  const open = (
    reconnect: boolean,
    onEvent: (event: StreamEvent) => void,
  ): SseHandle => {
    const cancel = vi.fn();
    streams.push({ reconnect, emit: onEvent, cancel });
    return { cancel };
  };
  const onLine = vi.fn();
  const onError = vi.fn();
  const stop = subscribeLogs({
    open,
    onLine,
    onError,
    retryDelayMs: 1_000,
    maxRetryDelayMs: 30_000,
    ...overrides,
  });
  return { streams, onLine, onError, stop };
}

describe("log stream subscription", () => {
  it("cancels the live stream before a retry opens the next one", async () => {
    vi.useFakeTimers();
    const { streams, onLine, onError, stop } = makeHarness();

    await vi.advanceTimersByTimeAsync(0);
    expect(streams).toHaveLength(1);
    const first = streams[0];
    if (!first) throw new Error("expected an initial stream");
    expect(first.reconnect).toBe(false);

    first.emit({ kind: "line", text: "hello" });
    first.emit({ kind: "error", message: "error: boom" });

    // The live handle is cancelled the moment the error lands, and no second stream exists yet: the
    // retry is only scheduled, so at most one stream is ever open.
    expect(onLine).toHaveBeenCalledWith("hello");
    expect(onError).toHaveBeenCalledWith("error: boom");
    expect(first.cancel).toHaveBeenCalledTimes(1);
    expect(streams).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1_000);

    // Exactly one new stream opens, reconnecting from the tail (a line was already received).
    expect(streams).toHaveLength(2);
    const second = streams[1];
    if (!second) throw new Error("expected a retry stream");
    expect(second.reconnect).toBe(true);

    stop();
    expect(second.cancel).toHaveBeenCalledTimes(1);
  });

  it("backs off exponentially on repeated errors and resets on a received line", async () => {
    vi.useFakeTimers();
    const { streams, stop } = makeHarness({ maxRetryDelayMs: 4_000 });

    await vi.advanceTimersByTimeAsync(0);
    streams[0]?.emit({ kind: "error", message: "down" });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(streams).toHaveLength(2);

    // Second failure waits 2s: at 1s nothing opens yet.
    streams[1]?.emit({ kind: "error", message: "down" });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(streams).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(streams).toHaveLength(3);

    // Third failure waits 4s (the cap).
    streams[2]?.emit({ kind: "error", message: "down" });
    await vi.advanceTimersByTimeAsync(3_999);
    expect(streams).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(streams).toHaveLength(4);

    // A received line resets the backoff to the base delay.
    streams[3]?.emit({ kind: "line", text: "recovered" });
    streams[3]?.emit({ kind: "error", message: "down" });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(streams).toHaveLength(5);

    stop();
  });

  it("always replays the tail on the first open of a subscription", async () => {
    vi.useFakeTimers();
    const { streams, stop } = makeHarness();

    await vi.advanceTimersByTimeAsync(0);
    expect(streams[0]?.reconnect).toBe(false);

    stop();
  });

  it("cancels the live stream on teardown", () => {
    const { streams, stop } = makeHarness();
    stop();
    expect(streams[0]?.cancel).toHaveBeenCalledTimes(1);
  });
});
