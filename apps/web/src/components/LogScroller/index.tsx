import { useRef, type ReactNode } from "react";
import { useLogWindow } from "./use-log-window";
import { useScrollFade } from "@/hooks/use-scroll-fade";
import { cn } from "@/lib/utils";

// The animated "streaming logs..." indicator shared by every log surface: three
// fading dots over a label, shown while a stream is live but has produced nothing yet.
export function StreamingIndicator() {
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

interface LogScrollerProps<T extends { id: number }> {
  lines: readonly T[];
  renderLine: (line: T) => ReactNode;
  // Shown in place of the lines while there are none.
  placeholder: ReactNode;
  // Rendered above the first line and below the last, so content clears the fade
  // and the tail never sits flush against an edge.
  topSpacer?: ReactNode;
  footer?: ReactNode;
  // Top/bottom edge fade offsets in px. Omit for a hard edge (embedded panes).
  fade?: { top: number; bottom: number };
  // Extra classes on the dark surface (e.g. the fullscreen "dark-overlay").
  className?: string;
}

// The one owner of the log look: a dark terminal surface that renders only the tail
// window of its lines (via useLogWindow), fades its top and bottom edges, and shows a
// placeholder while empty. Every log view (the agent Console, the gateway dialog) is a
// thin consumer that supplies its own lines, per-line rendering, and edge slots; this
// component owns the surface, the scroll, and the windowing.
export function LogScroller<T extends { id: number }>({
  lines,
  renderLine,
  placeholder,
  topSpacer,
  footer,
  fade,
  className,
}: LogScrollerProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);
  const { visibleCount, onScroll } = useLogWindow({
    parentRef,
    count: lines.length,
    newestId: lines.at(-1)?.id,
  });
  const visible = lines.slice(-visibleCount);

  // Fade only the edge that can still scroll, so the newest line at the bottom and the top of
  // the buffer never fade. Off entirely when the consumer sets no fade (the embedded console).
  const scrollFade = useScrollFade<HTMLDivElement>({
    ref: parentRef,
    top: fade ? `${String(fade.top)}px` : undefined,
    bottom: fade ? `${String(fade.bottom)}px` : undefined,
    // The top offset both callers pass clears a floating header, so it uses the under-chrome curve.
    topChrome: true,
  });
  const maskStyle = fade ? scrollFade.style : undefined;

  return (
    <div
      className={cn(
        "flex flex-col h-full dark bg-[#1a1a1a] text-[#e8e8e8]",
        className,
      )}
    >
      <div className="flex-1 min-h-0">
        <div
          ref={parentRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto overflow-x-hidden font-mono text-xs leading-[1.6] text-white/70"
          style={maskStyle}
        >
          {lines.length === 0 ? (
            placeholder
          ) : (
            <>
              {/* Only the tail window renders (useLogWindow); scrolling up grows it from
                  the buffer and settling at the bottom trims it back, so the DOM stays
                  bounded. Rows lay out for real, not behind a content-visibility size
                  estimate: lines wrap to unpredictable heights, so an estimate would
                  shift scrollHeight mid-scroll and make scrolling jump. */}
              {topSpacer}
              {visible.map(renderLine)}
              {footer}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
