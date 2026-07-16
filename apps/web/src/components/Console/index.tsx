import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useLayout } from "@/stores/use-layout";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";
import { logStreamAction, isAgentContainerUp } from "@/lib/log-stream-policy";
import type { AgentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_LINES = 5000;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
// One mono line is ~19px; wrapped lines measure taller (measureElement corrects).
const ESTIMATED_LINE_HEIGHT = 20;
// Render margin beyond the viewport so rows are measured before they scroll into view.
const OVERSCAN_ROWS = 16;
// How close to the bottom still counts as pinned for follow-on-append.
const AT_BOTTOM_THRESHOLD_PX = 80;
// The opening `tail -n N -f` dumps the recent tail back-to-back, then `-f` idles.
// We buffer that burst behind the "streaming logs..." placeholder and flush it as a
// single batch so the list mounts already-complete and one scrollToEnd lands at the
// true bottom (an incremental per-line fill leaves scroll short — rows re-measure
// taller than the estimate after the at-end gate has already dropped). Flush once the
// burst goes quiet for this long...
const INITIAL_FILL_QUIESCE_MS = 150;
// ...or this long has passed regardless, so a perpetually-chatty agent still renders.
const INITIAL_FILL_MAX_MS = 1500;

const LOG_LEVEL_TAGS = new Set([
  "DEBUG",
  "INFO",
  "WARNING",
  "ERROR",
  "CRITICAL",
]);
const FAMILY_TAGS = new Set(["AGENT", "SYSTEM", "USER", "EVENT"]);

const FAMILY_COLOR_CLASS: Record<string, string> = {
  AGENT: "text-fuchsia-300/90",
  SYSTEM: "text-green-300/90",
  USER: "text-white/90",
  EVENT: "text-yellow-300/90",
};

const SUBFAMILY_COLOR_CLASS: Record<string, Record<string, string>> = {
  AGENT: {
    ASSISTANT: "text-fuchsia-200/90",
    THINKING: "text-fuchsia-300/90",
    "TOOL CALL": "text-fuchsia-400/90",
    SUBAGENT: "text-fuchsia-500/90",
  },
  SYSTEM: {
    INIT: "text-green-200/90",
    STARTUP: "text-green-300/90",
    SHUTDOWN: "text-green-500/90",
    CLIENT: "text-green-400/90",
    DREAMER: "text-green-200/90",
    INTERRUPT: "text-green-500/90",
    PROACTIVE: "text-green-200/90",
    MESSAGE: "text-green-300/90",
    SDK: "text-green-500/90",
    USAGE: "text-green-400/90",
  },
  USER: {
    MESSAGE: "text-white/90",
  },
  EVENT: {
    NOTIFICATION: "text-yellow-200/90",
  },
};

function extractTags(line: string): string[] {
  return [...line.matchAll(/\[([A-Z ]+)\]/g)]
    .map((match) => match[1])
    .filter(
      (tag): tag is string => tag !== undefined && !LOG_LEVEL_TAGS.has(tag),
    );
}

function lineColorClass(line: string): string | null {
  const tags = extractTags(line);
  const familyIndex = tags.findIndex((tag) => FAMILY_TAGS.has(tag));
  if (familyIndex === -1) return null;

  const family = tags[familyIndex];
  if (family === undefined) return null;
  const subfamily = tags[familyIndex + 1];
  const subfamilyClass =
    subfamily === undefined
      ? undefined
      : SUBFAMILY_COLOR_CLASS[family]?.[subfamily];
  return subfamilyClass ?? FAMILY_COLOR_CLASS[family] ?? null;
}

interface LogLine {
  id: number;
  colorClass: string | null;
  html: string;
}

// "live" while the stream is healthy, "stopped" once the agent cleanly signals
// agent_stopped (terminal — no reconnect), "reconnecting" during transport-drop backoff.
type StreamState = "live" | "stopped" | "reconnecting";

const STREAM_NOTICE: Record<Exclude<StreamState, "live">, string> = {
  stopped: "— agent stopped —",
  reconnecting: "— reconnecting —",
};

function StreamNotice({ state }: { state: StreamState }) {
  if (state === "live") return null;
  return (
    <div className="text-center text-white/70 py-2">{STREAM_NOTICE[state]}</div>
  );
}

function StreamingPlaceholder({ state }: { state: StreamState }) {
  if (state !== "live") return <StreamNotice state={state} />;
  return (
    <div className="min-h-full flex flex-col items-center justify-end gap-2 py-10">
      <div className="flex items-center gap-1">
        <div className="size-[5px] rounded-full bg-white/30 opacity-60" />
        <div className="size-[5px] rounded-full bg-white/30 opacity-40" />
        <div className="size-[5px] rounded-full bg-white/30 opacity-20" />
      </div>
      <span className="text-xs text-white/70">streaming logs...</span>
    </div>
  );
}

interface ConsoleProps {
  name: string;
  status: AgentStatus;
  fullscreen?: boolean;
}

export function Console({ name, status, fullscreen }: ConsoleProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [streamState, setStreamState] = useState<StreamState>("live");
  const idRef = useRef(0);
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  // Initial replay-tail buffering: while `fillingRef` is set, appended lines collect
  // in `bufferRef` instead of `lines`, then flush as one batch (see the FILL consts).
  const fillingRef = useRef(true);
  const bufferRef = useRef<LogLine[]>([]);
  const quiesceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const capTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushBuffer = useCallback(() => {
    if (!fillingRef.current) return;
    fillingRef.current = false;
    if (quiesceTimerRef.current) clearTimeout(quiesceTimerRef.current);
    if (capTimerRef.current) clearTimeout(capTimerRef.current);
    quiesceTimerRef.current = null;
    capTimerRef.current = null;
    const buffered = bufferRef.current;
    bufferRef.current = [];
    setLines(
      buffered.length > MAX_LINES ? buffered.slice(-MAX_LINES) : buffered,
    );
  }, []);

  const connect = useRef<(replay: boolean) => void>(undefined);

  useEffect(() => {
    connect.current = (replay: boolean) => {
      if (!name || !activeRef.current) return;
      void stopLogs(name);
      setStreamState("live");
      // Only a fresh replay connect buffers a tail; a reconnect (tail=0) appends live.
      fillingRef.current = replay;
      bufferRef.current = [];
      if (quiesceTimerRef.current) clearTimeout(quiesceTimerRef.current);
      if (capTimerRef.current) clearTimeout(capTimerRef.current);
      quiesceTimerRef.current = null;
      capTimerRef.current = null;

      streamLogs(
        name,
        (event) => {
          const action = logStreamAction(event);
          switch (action.kind) {
            case "append": {
              // A line means the connection is healthy, so reset the backoff.
              reconnectDelayRef.current = RECONNECT_BASE;
              const stripped = stripAnsi(action.text);
              const line = {
                id: idRef.current++,
                colorClass: lineColorClass(stripped),
                html: linkify(stripped),
              };
              if (fillingRef.current) {
                // Buffer the opening tail; flush on quiescence or the max cap.
                bufferRef.current.push(line);
                if (quiesceTimerRef.current)
                  clearTimeout(quiesceTimerRef.current);
                quiesceTimerRef.current = setTimeout(
                  flushBuffer,
                  INITIAL_FILL_QUIESCE_MS,
                );
                capTimerRef.current ??= setTimeout(
                  flushBuffer,
                  INITIAL_FILL_MAX_MS,
                );
                break;
              }
              setLines((prev) => {
                const next = [...prev, line];
                return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
              });
              break;
            }
            case "stopped":
              // agent_stopped is a clean terminal signal, not a failure: show the
              // final tail and wait. A restart re-streams via the status effect
              // below, so we never blind-reconnect against a stopped container.
              flushBuffer();
              setStreamState("stopped");
              break;
            case "reconnect":
              // A transport drop while the agent is up: reconnect with backoff,
              // requesting no replay (tail=0) so the tail isn't re-appended. Surface
              // any partial buffered tail first so we never drop it on the way down.
              flushBuffer();
              setStreamState("reconnecting");
              if (activeRef.current) {
                reconnectTimerRef.current = setTimeout(() => {
                  reconnectDelayRef.current = Math.min(
                    reconnectDelayRef.current * 2,
                    RECONNECT_MAX,
                  );
                  connect.current?.(false);
                }, reconnectDelayRef.current);
              }
              break;
          }
        },
        { replay },
      ).catch((err: unknown) => {
        console.warn("[console] log stream failed:", err);
      });
    };
  });

  // Open a fresh stream on mount / agent switch. Status changes are handled by the
  // resume effect below, so a stop doesn't clear and re-dump the final tail.
  useEffect(() => {
    activeRef.current = true;
    idRef.current = 0;
    setLines([]);
    reconnectDelayRef.current = RECONNECT_BASE;
    connect.current?.(true);
    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (quiesceTimerRef.current) clearTimeout(quiesceTimerRef.current);
      if (capTimerRef.current) clearTimeout(capTimerRef.current);
      if (name) void stopLogs(name);
    };
  }, [name]);

  // Resume a fresh stream only when the agent comes back up after a stop. We never
  // re-stream on the down transition (that re-dumped the same final tail), and never
  // poll a stopped agent — the authoritative status tells us when it's back.
  const prevStatusRef = useRef(status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    // Only a genuine status change matters; streamState is a dep purely so the
    // guard reads the current liveness, and the prev === status check makes
    // streamState-only re-runs no-ops.
    if (prev === status || streamState === "live") return;
    if (isAgentContainerUp(status)) {
      idRef.current = 0;
      setLines([]);
      reconnectDelayRef.current = RECONNECT_BASE;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      connect.current?.(true);
    }
  }, [status, streamState]);

  const parentRef = useRef<HTMLDivElement>(null);
  const count = lines.length;

  const getItemKey = useCallback(
    (index: number) => lines[index]?.id ?? index,
    [lines],
  );

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATED_LINE_HEIGHT,
    getItemKey,
    // End-anchored stream: stick to the bottom on new lines (unless the user scrolled up),
    // and stay anchored when old lines drop off the front at the MAX_LINES cap.
    anchorTo: "end",
    followOnAppend: true,
    scrollEndThreshold: AT_BOTTOM_THRESHOLD_PX,
    overscan: OVERSCAN_ROWS,
    directDomUpdates: true,
  });

  // Jump to the bottom when the buffered tail first lands (count 0 -> N in one batch),
  // and again whenever the list resets to empty (agent switch / resume) and refills.
  // Because the list mounts already-complete, one scrollToEnd + the virtualizer's
  // reconcile loop reaches the true bottom; from then on anchorTo:"end" +
  // followOnAppend keep the live tail pinned.
  const hadLinesRef = useRef(false);
  useLayoutEffect(() => {
    const hasLines = count > 0;
    if (hasLines && !hadLinesRef.current) virtualizer.scrollToEnd();
    hadLinesRef.current = hasLines;
  }, [count, virtualizer]);

  const items = virtualizer.getVirtualItems();
  const linePad = fullscreen ? "px-page" : "px-5";

  return (
    <div
      className={cn(
        "flex flex-col h-full dark bg-[#1a1a1a] text-[#e8e8e8]",
        fullscreen && "dark-overlay",
      )}
    >
      <div className="flex-1 min-h-0">
        <div
          ref={parentRef}
          className="h-full overflow-y-auto overflow-x-hidden font-mono text-xs leading-[1.6] text-white/70"
          style={
            fullscreen
              ? {
                  maskImage: `linear-gradient(to bottom, transparent, black ${String(navbarHeight * 2)}px, black calc(100% - 15px), transparent)`,
                }
              : undefined
          }
        >
          {count === 0 ? (
            <StreamingPlaceholder state={streamState} />
          ) : (
            <div
              ref={virtualizer.containerRef}
              style={{ position: "relative", width: "100%" }}
            >
              {items.map((item) => {
                const line = lines[item.index];
                if (!line) return null;
                const isFirst = item.index === 0;
                const isLast = item.index === count - 1;
                return (
                  <div
                    key={item.key}
                    ref={virtualizer.measureElement}
                    data-index={item.index}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                    }}
                  >
                    {isFirst &&
                      (fullscreen ? (
                        <div
                          style={{
                            height: `calc(${String(navbarHeight)}px + var(--page-padding-x))`,
                          }}
                        />
                      ) : (
                        <div className="h-6" />
                      ))}
                    <div
                      className={cn(
                        "break-words whitespace-pre-wrap",
                        linePad,
                        line.colorClass,
                      )}
                      dangerouslySetInnerHTML={{ __html: line.html }}
                    />
                    {isLast && (
                      <div className={fullscreen ? "pb-page" : "pb-6"}>
                        <StreamNotice state={streamState} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
