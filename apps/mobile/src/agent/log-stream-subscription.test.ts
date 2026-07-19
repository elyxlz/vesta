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
  it("cancels the live stream before a retry opens the next one", () => {
    vi.useFakeTimers();
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
    });

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

    vi.advanceTimersByTime(1_000);

    // Exactly one new stream opens, reconnecting from the tail (a line was already received).
    expect(streams).toHaveLength(2);
    const second = streams[1];
    if (!second) throw new Error("expected a retry stream");
    expect(second.reconnect).toBe(true);

    stop();
    expect(second.cancel).toHaveBeenCalledTimes(1);
  });
});
