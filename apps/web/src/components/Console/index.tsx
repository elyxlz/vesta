import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useLayout } from "@/stores/use-layout";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";
import { logStreamAction } from "@/lib/log-stream-policy";
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
    .filter((tag) => !LOG_LEVEL_TAGS.has(tag));
}

function lineColorClass(line: string): string | null {
  const tags = extractTags(line);
  const familyIndex = tags.findIndex((tag) => FAMILY_TAGS.has(tag));

  if (familyIndex !== -1) {
    const family = tags[familyIndex];
    const subfamily = tags[familyIndex + 1];
    return (
      (subfamily && SUBFAMILY_COLOR_CLASS[family]?.[subfamily]) ||
      FAMILY_COLOR_CLASS[family] ||
      null
    );
  }

  return null;
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
    <div className="min-h-full flex flex-col items-center justify-end gap-2 py-1">
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
  onClose?: () => void;
  fullscreen?: boolean;
}

export function Console({ name, status, onClose, fullscreen }: ConsoleProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [streamState, setStreamState] = useState<StreamState>("live");
  const idRef = useRef(0);
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  const connect = useRef<(replay: boolean) => void>(undefined);

  useEffect(() => {
    connect.current = (replay: boolean) => {
      if (!name || !activeRef.current) return;
      stopLogs(name);
      setStreamState("live");

      streamLogs(
        name,
        (event) => {
          const action = logStreamAction(event);
          switch (action.kind) {
            case "append": {
              // A line means the connection is healthy, so reset the backoff.
              reconnectDelayRef.current = RECONNECT_BASE;
              const stripped = stripAnsi(action.text);
              setLines((prev) => {
                const next = [
                  ...prev,
                  {
                    id: idRef.current++,
                    colorClass: lineColorClass(stripped),
                    html: linkify(stripped),
                  },
                ];
                return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
              });
              break;
            }
            case "stopped":
              // agent_stopped is a clean terminal signal, not a failure: show the
              // final tail and wait. A restart re-streams via the status effect
              // below, so we never blind-reconnect against a stopped container.
              setStreamState("stopped");
              break;
            case "reconnect":
              // A transport drop while the agent is up: reconnect with backoff,
              // requesting no replay (tail=0) so the tail isn't re-appended.
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
      );
    };
  });

  // Re-keyed on status so an agent start/stop/restart re-streams a fresh tail;
  // within a session, transport drops reconnect (tail=0) without re-keying.
  useEffect(() => {
    activeRef.current = true;
    idRef.current = 0;
    setLines([]);
    reconnectDelayRef.current = RECONNECT_BASE;
    connect.current?.(true);
    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (name) stopLogs(name);
    };
  }, [name, status]);

  useEffect(() => {
    if (!onClose) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const parentRef = useRef<HTMLDivElement>(null);
  const count = lines.length;

  const getItemKey = useCallback((index: number) => lines[index].id, [lines]);

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

  // Snap to the latest line when the stream first produces output (and after an agent
  // switch resets the list).
  const hadLinesRef = useRef(false);
  useLayoutEffect(() => {
    const has = count > 0;
    if (has && !hadLinesRef.current) virtualizer.scrollToEnd();
    hadLinesRef.current = has;
  }, [count, virtualizer]);

  const items = virtualizer.getVirtualItems();
  const linePad = fullscreen ? "px-page" : "px-3";

  return (
    <div
      className={cn(
        "flex flex-col h-full",
        fullscreen && "dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8]",
      )}
    >
      {!fullscreen && (
        <div className="flex items-center justify-between px-4 py-3 min-h-11 shrink-0 border-b border-white/5">
          <span className="text-sm font-medium">{name} logs</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-9"
                aria-label="close logs"
                onClick={onClose}
              >
                <X className="size-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>close</TooltipContent>
          </Tooltip>
        </div>
      )}

      <div className="flex-1 min-h-0">
        <div
          ref={parentRef}
          className="h-full overflow-y-auto overflow-x-hidden font-mono text-xs leading-[1.6] text-white/70"
          style={
            fullscreen
              ? {
                  maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * 2}px, black calc(100% - 15px), transparent)`,
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
                            height: `calc(${navbarHeight}px + var(--page-padding-x))`,
                          }}
                        />
                      ) : (
                        <div className="h-2" />
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
                      <div className={fullscreen ? "pb-page" : "pb-2"}>
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
