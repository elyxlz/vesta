import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LogEvent } from "@/lib/types";
import { LOG_SCROLLBACK_LINES } from "@/lib/log-stream-policy";
import {
  createLogSession,
  INITIAL_FILL_MAX_MS,
  INITIAL_FILL_QUIESCE_MS,
  RECONNECT_BASE,
  RECONNECT_MAX,
  type LogSession,
} from "./log-session";

interface StreamCall {
  replay: boolean;
  emit: (event: LogEvent) => void;
}

function makeHarness() {
  const calls: StreamCall[] = [];
  const streamLogs = vi.fn(
    (
      _name: string,
      onEvent: (event: LogEvent) => void,
      opts?: { replay?: boolean },
    ) => {
      calls.push({ replay: opts?.replay ?? true, emit: onEvent });
      return new Promise<void>(() => undefined);
    },
  );
  const stopLogs = vi.fn(() => Promise.resolve());
  const session = createLogSession({
    name: "ada",
    streamLogs,
    stopLogs,
    renderLine: (text: string) => `<i>${text}</i>`,
  });
  const call = (index: number): StreamCall => {
    const found = calls[index];
    if (!found) throw new Error(`no stream call ${String(index)}`);
    return found;
  };
  return { call, streamLogs, stopLogs, session };
}

function emitLines(call: StreamCall, texts: string[]): void {
  for (const text of texts) call.emit({ kind: "Line", text });
}

function lineHtml(session: LogSession): string[] {
  return session.getSnapshot().lines.map((line) => line.html);
}

describe("log session", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not connect before start, and start is idempotent", () => {
    const { streamLogs, session } = makeHarness();
    expect(streamLogs).not.toHaveBeenCalled();
    session.start();
    session.start();
    expect(streamLogs).toHaveBeenCalledTimes(1);
  });

  it("buffers the opening tail and flushes it as one batch after the burst quiesces", () => {
    const { call, session } = makeHarness();
    const changes = vi.fn();
    session.subscribe(changes);
    session.start();
    emitLines(call(0), ["a", "b", "c"]);
    expect(session.getSnapshot().lines).toHaveLength(0);
    vi.advanceTimersByTime(INITIAL_FILL_QUIESCE_MS);
    expect(lineHtml(session)).toEqual(["<i>a</i>", "<i>b</i>", "<i>c</i>"]);
    expect(changes).toHaveBeenCalled();
  });

  it("flushes a perpetually chatty tail at the max fill cap", () => {
    const { call, session } = makeHarness();
    session.start();
    // Lines land faster than the quiesce window, so only the cap can flush.
    const interval = INITIAL_FILL_QUIESCE_MS - 50;
    const ticks = Math.ceil(INITIAL_FILL_MAX_MS / interval);
    for (let tick = 0; tick < ticks; tick += 1) {
      emitLines(call(0), ["tick"]);
      vi.advanceTimersByTime(interval);
    }
    expect(session.getSnapshot().lines.length).toBeGreaterThan(0);
  });

  it("caps the scrollback at LOG_SCROLLBACK_LINES, dropping the oldest", () => {
    const { call, session } = makeHarness();
    session.start();
    emitLines(
      call(0),
      Array.from(
        { length: LOG_SCROLLBACK_LINES + 5 },
        (_, i) => `l${String(i)}`,
      ),
    );
    vi.advanceTimersByTime(INITIAL_FILL_QUIESCE_MS);
    const lines = session.getSnapshot().lines;
    expect(lines).toHaveLength(LOG_SCROLLBACK_LINES);
    expect(lines[0]?.html).toBe("<i>l5</i>");
  });

  it("appends live lines after the fill flush and notifies subscribers", () => {
    const { call, session } = makeHarness();
    session.start();
    emitLines(call(0), ["tail"]);
    vi.advanceTimersByTime(INITIAL_FILL_QUIESCE_MS);
    const changes = vi.fn();
    session.subscribe(changes);
    emitLines(call(0), ["live"]);
    expect(lineHtml(session)).toEqual(["<i>tail</i>", "<i>live</i>"]);
    expect(changes).toHaveBeenCalledTimes(1);
  });

  it("a clean agent_stopped is terminal: no reconnect is scheduled", () => {
    const { call, streamLogs, session } = makeHarness();
    session.start();
    emitLines(call(0), ["bye"]);
    call(0).emit({ kind: "End" });
    expect(session.getSnapshot().streamState).toBe("stopped");
    expect(lineHtml(session)).toEqual(["<i>bye</i>"]);
    vi.advanceTimersByTime(60_000);
    expect(streamLogs).toHaveBeenCalledTimes(1);
  });

  it("a transport error reconnects after the backoff without replay", () => {
    const { call, streamLogs, session } = makeHarness();
    session.start();
    emitLines(call(0), ["tail"]);
    vi.advanceTimersByTime(INITIAL_FILL_QUIESCE_MS);
    call(0).emit({ kind: "Error", message: "gone" });
    expect(session.getSnapshot().streamState).toBe("reconnecting");
    vi.advanceTimersByTime(RECONNECT_BASE);
    expect(streamLogs).toHaveBeenCalledTimes(2);
    expect(call(1).replay).toBe(false);
    expect(session.getSnapshot().streamState).toBe("live");
    emitLines(call(1), ["more"]);
    expect(lineHtml(session)).toEqual(["<i>tail</i>", "<i>more</i>"]);
  });

  it("backoff doubles per consecutive failure and resets on a healthy line", () => {
    const { call, streamLogs, session } = makeHarness();
    session.start();
    call(0).emit({ kind: "Error", message: "gone" });
    vi.advanceTimersByTime(RECONNECT_BASE);
    expect(streamLogs).toHaveBeenCalledTimes(2);
    call(1).emit({ kind: "Error", message: "gone" });
    vi.advanceTimersByTime(RECONNECT_BASE);
    expect(streamLogs).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(RECONNECT_BASE);
    expect(streamLogs).toHaveBeenCalledTimes(3);
    emitLines(call(2), ["healthy"]);
    call(2).emit({ kind: "Error", message: "gone" });
    vi.advanceTimersByTime(RECONNECT_BASE);
    expect(streamLogs).toHaveBeenCalledTimes(4);
  });

  it("backoff never exceeds RECONNECT_MAX", () => {
    const { call, streamLogs, session } = makeHarness();
    session.start();
    // Enough consecutive failures that unbounded doubling would pass the ceiling.
    const failures = Math.ceil(Math.log2(RECONNECT_MAX / RECONNECT_BASE)) + 2;
    for (let attempt = 0; attempt < failures; attempt += 1) {
      call(attempt).emit({ kind: "Error", message: "gone" });
      vi.advanceTimersByTime(RECONNECT_MAX);
    }
    const connectsBefore = streamLogs.mock.calls.length;
    call(failures).emit({ kind: "Error", message: "gone" });
    vi.advanceTimersByTime(RECONNECT_MAX - 1);
    expect(streamLogs).toHaveBeenCalledTimes(connectsBefore);
    vi.advanceTimersByTime(1);
    expect(streamLogs).toHaveBeenCalledTimes(connectsBefore + 1);
  });

  it("a status up-transition after a stop restarts a fresh replay stream", () => {
    const { call, streamLogs, session } = makeHarness();
    session.setStatus("alive");
    session.start();
    emitLines(call(0), ["final tail"]);
    call(0).emit({ kind: "End" });
    session.setStatus("stopped");
    expect(streamLogs).toHaveBeenCalledTimes(1);
    session.setStatus("alive");
    expect(streamLogs).toHaveBeenCalledTimes(2);
    expect(call(1).replay).toBe(true);
    expect(session.getSnapshot().lines).toHaveLength(0);
    expect(session.getSnapshot().streamState).toBe("live");
  });

  it("a status change while the stream is live does not reconnect", () => {
    const { streamLogs, session } = makeHarness();
    session.setStatus("alive");
    session.start();
    session.setStatus("starting");
    session.setStatus("alive");
    expect(streamLogs).toHaveBeenCalledTimes(1);
  });

  it("dispose cancels the pending reconnect and stops the stream", () => {
    const { call, streamLogs, stopLogs, session } = makeHarness();
    session.start();
    call(0).emit({ kind: "Error", message: "gone" });
    session.dispose();
    vi.advanceTimersByTime(60_000);
    expect(streamLogs).toHaveBeenCalledTimes(1);
    expect(stopLogs).toHaveBeenCalledWith("ada");
  });
});
