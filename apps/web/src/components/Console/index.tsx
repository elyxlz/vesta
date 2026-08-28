import { useEffect, useSyncExternalStore } from "react";
import { useLayout } from "@/stores/use-layout";
import type { LogStreamState } from "@/lib/log-session";
import { useAgentLogSession } from "@/providers/AgentLogStreamProvider";
import { LogScroller, StreamingIndicator } from "@/components/LogScroller";
import { BOTTOM_FADE_PX } from "@/hooks/use-scroll-fade";
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
  return <StreamingIndicator />;
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

  const lineClass = cn(
    "break-words whitespace-pre-wrap",
    fullscreen ? "px-page" : "px-5",
  );

  return (
    <LogScroller
      lines={lines}
      className={fullscreen ? "dark-overlay" : undefined}
      fade={
        fullscreen
          ? { top: navbarHeight * 2, bottom: BOTTOM_FADE_PX }
          : undefined
      }
      placeholder={<StreamingPlaceholder state={streamState} />}
      topSpacer={
        fullscreen ? (
          <div
            style={{
              height: `calc(${String(navbarHeight)}px + var(--page-padding-x))`,
            }}
          />
        ) : (
          <div className="h-6" />
        )
      }
      footer={
        <div className={fullscreen ? "pb-page" : "pb-6"}>
          <StreamNotice state={streamState} />
        </div>
      }
      renderLine={(line) => (
        <div
          key={line.id}
          className={lineClass}
          dangerouslySetInnerHTML={{ __html: line.html }}
        />
      )}
    />
  );
}
