import type { AgentStatus } from "@vesta/core";
import {
  isAgentContainerUp,
  LOG_SCROLLBACK_LINES,
  logStreamAction,
} from "@/lib/log-stream-policy";
import type { LogEvent } from "@/lib/types";

export const RECONNECT_BASE = 1000;
export const RECONNECT_MAX = 30000;
// The opening `tail -n N -f` dumps the recent tail back-to-back, then `-f` idles.
// We buffer that burst and flush it as a single batch so the viewer mounts
// already-complete and one scroll-to-bottom lands at the true bottom. Flush once
// the burst goes quiet for this long...
export const INITIAL_FILL_QUIESCE_MS = 150;
// ...or this long has passed regardless, so a perpetually-chatty agent still renders.
export const INITIAL_FILL_MAX_MS = 1500;

interface LogLine {
  id: number;
  html: string;
}

// "live" while the stream is healthy, "stopped" once the agent cleanly signals
// agent_stopped (terminal — no reconnect), "reconnecting" during transport-drop backoff.
export type LogStreamState = "live" | "stopped" | "reconnecting";

interface LogSnapshot {
  lines: readonly LogLine[];
  streamState: LogStreamState;
}

export interface LogSessionDeps {
  name: string;
  streamLogs: (
    name: string,
    onEvent: (event: LogEvent) => void,
    opts?: { replay?: boolean },
  ) => Promise<void>;
  stopLogs: (name: string) => Promise<void>;
  renderLine: (text: string) => string;
}

export interface LogSession {
  start: () => void;
  setStatus: (status: AgentStatus) => void;
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => LogSnapshot;
  dispose: () => void;
}

// The one owner of an agent's log stream: connect, buffer the opening tail,
// cap the scrollback, back off through transport drops, stop cleanly on
// agent_stopped, and resume when the authoritative status says the container is
// back up. Framework-free so the whole lifecycle is unit-testable; the provider
// adapts it to React via subscribe/getSnapshot.
export function createLogSession(deps: LogSessionDeps): LogSession {
  let snapshot: LogSnapshot = { lines: [], streamState: "live" };
  const listeners = new Set<() => void>();

  let started = false;
  let disposed = false;
  let nextId = 0;
  let reconnectDelay = RECONNECT_BASE;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let prevStatus: AgentStatus | null = null;

  // While filling, appended lines collect in `buffer` instead of the snapshot,
  // then flush as one batch (see the FILL consts above).
  let filling = false;
  let buffer: LogLine[] = [];
  let quiesceTimer: ReturnType<typeof setTimeout> | null = null;
  let capTimer: ReturnType<typeof setTimeout> | null = null;

  const publish = (next: Partial<LogSnapshot>): void => {
    snapshot = { ...snapshot, ...next };
    for (const listener of listeners) listener();
  };

  const clearFillTimers = (): void => {
    if (quiesceTimer) clearTimeout(quiesceTimer);
    if (capTimer) clearTimeout(capTimer);
    quiesceTimer = null;
    capTimer = null;
  };

  const capped = (lines: LogLine[]): LogLine[] =>
    lines.length > LOG_SCROLLBACK_LINES
      ? lines.slice(-LOG_SCROLLBACK_LINES)
      : lines;

  const flushBuffer = (): void => {
    if (!filling) return;
    filling = false;
    clearFillTimers();
    const buffered = buffer;
    buffer = [];
    publish({ lines: capped(buffered) });
  };

  const append = (text: string): void => {
    // A line means the connection is healthy, so reset the backoff.
    reconnectDelay = RECONNECT_BASE;
    const line = { id: nextId++, html: deps.renderLine(text) };
    if (filling) {
      buffer.push(line);
      if (quiesceTimer) clearTimeout(quiesceTimer);
      quiesceTimer = setTimeout(flushBuffer, INITIAL_FILL_QUIESCE_MS);
      capTimer ??= setTimeout(flushBuffer, INITIAL_FILL_MAX_MS);
      return;
    }
    publish({ lines: capped([...snapshot.lines, line]) });
  };

  const connect = (replay: boolean): void => {
    if (disposed) return;
    publish({ streamState: "live" });
    // Only a fresh replay connect buffers a tail; a reconnect (tail=0) appends live.
    filling = replay;
    buffer = [];
    clearFillTimers();

    void deps.streamLogs(
      deps.name,
      (event) => {
        const action = logStreamAction(event);
        switch (action.kind) {
          case "append":
            append(action.text);
            break;
          case "stopped":
            // agent_stopped is a clean terminal signal, not a failure: show the
            // final tail and wait. A restart re-streams via setStatus, so we
            // never blind-reconnect against a stopped container.
            flushBuffer();
            publish({ streamState: "stopped" });
            break;
          case "reconnect":
            // A transport drop while the agent is up: reconnect with backoff,
            // requesting no replay (tail=0) so the tail isn't re-appended. Surface
            // any partial buffered tail first so we never drop it on the way down.
            flushBuffer();
            publish({ streamState: "reconnecting" });
            if (!disposed) {
              reconnectTimer = setTimeout(() => {
                reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
                connect(false);
              }, reconnectDelay);
            }
            break;
        }
      },
      { replay },
    );
  };

  return {
    start: () => {
      if (started || disposed) return;
      started = true;
      connect(true);
    },
    setStatus: (status: AgentStatus) => {
      const prev = prevStatus;
      prevStatus = status;
      // Resume a fresh stream only when the agent comes back up after a stop. We
      // never re-stream on the down transition (that re-dumped the same final
      // tail), and never poll a stopped agent.
      if (!started || prev === null || prev === status) return;
      if (snapshot.streamState === "live" || !isAgentContainerUp(status))
        return;
      nextId = 0;
      reconnectDelay = RECONNECT_BASE;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      publish({ lines: [] });
      connect(true);
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    dispose: () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearFillTimers();
      void deps.stopLogs(deps.name);
    },
  };
}
