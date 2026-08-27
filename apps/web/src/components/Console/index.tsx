import { useEffect, useRef, useSyncExternalStore } from "react";
import { useLayout } from "@/stores/use-layout";
import type { LogStreamState } from "@/lib/log-session";
import { useLogWindow } from "@/lib/use-log-window";
import { useAgentLogSession } from "@/providers/AgentLogStreamProvider";
import { cn } from "@/lib/utils";

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

  const parentRef = useRef<HTMLDivElement>(null);
  const { visibleCount, onScroll } = useLogWindow({
    parentRef,
    count: lines.length,
    newestId: lines.at(-1)?.id,
  });
  const visible = lines.slice(-visibleCount);

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
          onScroll={onScroll}
          className="h-full overflow-y-auto overflow-x-hidden font-mono text-xs leading-[1.6] text-white/70"
          style={
            fullscreen
              ? {
                  maskImage: `linear-gradient(to bottom, transparent, black ${String(navbarHeight * 2)}px, black calc(100% - 15px), transparent)`,
                }
              : undefined
          }
        >
          {lines.length === 0 ? (
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
              {/* Only the tail window renders (useLogWindow); scrolling up grows it from the
                  buffer and settling at the bottom trims it back, so the DOM stays bounded.
                  Rows lay out for real, not behind a content-visibility size estimate: lines
                  wrap to unpredictable heights, so an estimate would shift scrollHeight
                  mid-scroll and make scrolling jump. */}
              {visible.map((line) => (
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
