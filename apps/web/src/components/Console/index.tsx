import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
} from "react";
import { useLayout } from "@/stores/use-layout";
import type { LogStreamState } from "@/lib/log-session";
import { useAgentLogSession } from "@/providers/AgentLogStreamProvider";
import { cn } from "@/lib/utils";

// How close to the bottom still counts as pinned for follow-on-append.
const AT_BOTTOM_THRESHOLD_PX = 80;

const STREAM_NOTICE: Record<Exclude<LogStreamState, "live">, string> = {
  stopped: "— agent stopped —",
  reconnecting: "— reconnecting —",
};

function StreamNotice({ state }: { state: LogStreamState }) {
  if (state === "live") return null;
  return (
    <div className="text-center text-white/70 py-2">{STREAM_NOTICE[state]}</div>
  );
}

function StreamingPlaceholder({ state }: { state: LogStreamState }) {
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

// The log viewer: a pure view over the layout-held log session, which owns the
// stream, the scrollback, and reconnects. Mounting (or an Activity pane turning
// visible) starts the session; the session outlives this view, so returning here
// re-renders the accumulated buffer instead of re-streaming a tail.
export function Console({ fullscreen }: { fullscreen?: boolean }) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const session = useAgentLogSession();
  const { lines, streamState } = useSyncExternalStore(
    session.subscribe,
    session.getSnapshot,
  );

  useEffect(() => {
    session.start();
  }, [session]);

  // Follow the tail unless the user has scrolled up; true whenever the list is (re)filled.
  const pinnedRef = useRef(true);
  const parentRef = useRef<HTMLDivElement>(null);
  const count = lines.length;
  // `count` stops changing once the scrollback cap is full, but the tail still
  // advances as old lines are dropped. Key follow-on-append to the newest line
  // instead so a full console continues to follow live output.
  const newestLineId = lines.at(-1)?.id;

  useEffect(() => {
    if (count === 0) pinnedRef.current = true;
  }, [count]);

  const updatePinned = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    pinnedRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <=
      AT_BOTTOM_THRESHOLD_PX;
  }, []);

  // Follow the tail on append, and jump to the bottom when the buffered tail first
  // lands or the list refills after an agent switch/resume, unless the user scrolled up.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el && count > 0 && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [count, newestLineId]);

  const lineClass = cn(
    "break-words whitespace-pre-wrap",
    fullscreen ? "px-page" : "px-5",
  );

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
          onScroll={updatePinned}
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
            <>
              {fullscreen ? (
                <div
                  style={{
                    height: `calc(${String(navbarHeight)}px + var(--page-padding-x))`,
                  }}
                />
              ) : (
                <div className="h-6" />
              )}
              {/* Every log line stays in the DOM (no windowing) so a native text selection
                  survives scrolling and copies the full range. Rows must lay out for real,
                  not behind a content-visibility size estimate: lines wrap to unpredictable
                  heights, and an estimate makes scrollHeight shift mid-scroll, so scrolling
                  jumps. */}
              {lines.map((line) => (
                <div
                  key={line.id}
                  className={lineClass}
                  dangerouslySetInnerHTML={{ __html: line.html }}
                />
              ))}
              <div className={fullscreen ? "pb-page" : "pb-6"}>
                <StreamNotice state={streamState} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
