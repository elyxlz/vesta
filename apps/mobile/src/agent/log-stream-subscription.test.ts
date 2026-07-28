import { afterEach, describe, expect, it, vi } from "vitest";
import type { SseHandle, StreamEvent } from "@vesta/core";
import { subscribeLogs } from "./log-stream-subscription";

interface FakeStream {
  reconnect: boolean;
  emit: (event: StreamEvent) => void;
  cancel: ReturnType<typeof vi.fn>;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("log stream subscription", () => {
  it("cancels the live stream before a retry opens the next one", async () => {
    vi.useFakeTimers();
    const streams: FakeStream[] = [];
    const open = (
      reconnect: boolean,
      onEvent: (event: StreamEvent) => void,
    ): Promise<SseHandle> => {
      const cancel = vi.fn();
      streams.push({ reconnect, emit: onEvent, cancel });
      return Promise.resolve({ cancel });
    };
    const onLine = vi.fn();
    const onError = vi.fn();

    const stop = subscribeLogs({
      open,
      onLine,
      onError,
      retryDelayMs: 1_000,
    });

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

  it("cancels a stream that opens after teardown", async () => {
    // The URL is built asynchronously (it refreshes the token), so teardown can land while the
    // first open is still in flight; without the post-await check that stream would leak.
    const cancel = vi.fn();
    let release = (): void => undefined;
    const open = (): Promise<SseHandle> =>
      new Promise<SseHandle>((resolve) => {
        release = () => resolve({ cancel });
      });

    const stop = subscribeLogs({
      open,
      onLine: vi.fn(),
      onError: vi.fn(),
      retryDelayMs: 1_000,
    });
    stop();
    release();
    await Promise.resolve();
    await Promise.resolve();

    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
