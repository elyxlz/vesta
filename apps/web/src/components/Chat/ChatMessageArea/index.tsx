import {
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CardContent } from "@/components/ui/card";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { stepTransition } from "@/lib/motion";
import { ChatBubble } from "../ChatBubble";
import { buildDecorated } from "./virtual";

// First-paint estimates per row kind (actual heights are measured). Tool-call rows are
// much shorter than message bubbles; estimating them all at the message height made the
// virtualizer over-correct on every tool row that scrolled into view, which read as jank.
const ESTIMATED_MESSAGE_HEIGHT = 64;
const ESTIMATED_TOOL_HEIGHT = 30;
// How close to the bottom (px) still counts as "pinned" — drives follow-on-append and
// gates the load-older check (don't page up while sitting at the bottom).
const AT_BOTTOM_THRESHOLD_PX = 80;
// Scrolling within this many px of the top loads the previous page.
const LOAD_OLDER_TOP_PX = 120;
// Rows rendered beyond the visible window on each side — a measurement margin. Bigger =
// rows are rendered and measured BEFORE they scroll into view, so they appear at their real
// height instead of resizing in front of you (this is the "measure then show" that smooths
// scroll-up and prepends). Small values make the mount/unmount visible for debugging.
const OVERSCAN_ROWS = 12;

export interface ChatScrollHandle {
  scrollToBottom: () => void;
}

interface ChatMessageAreaProps {
  scrollRef: RefObject<ChatScrollHandle | null>;
  loadMore: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  fullscreen?: boolean;
  navbarHeight: number;
  chatMessages: VestaEvent[];
  connected: boolean;
  historyLoaded: boolean;
  agentName: string;
  notAuthenticated: boolean;
  isTyping: boolean;
  isMobile: boolean;
}

// Placeholder bubbles shown while the first page of history is in flight, so a slow
// load reads as a conversation arriving rather than an empty/"needs to sign in" state.
// Mirrors ChatBubble: bg-secondary on the left (agent), bg-primary on the right (you),
// clustered into runs like a real chat. The column is bottom-anchored and overflows the
// top, so it reads as a thread continuing above the fold.
const SKELETON_ROWS: { side: "agent" | "user"; size: string }[] = [
  { side: "agent", size: "h-9 w-40" },
  { side: "agent", size: "h-14 w-56" },
  { side: "user", size: "h-9 w-28" },
  { side: "user", size: "h-9 w-44" },
  { side: "user", size: "h-9 w-24" },
  { side: "agent", size: "h-9 w-48" },
  { side: "agent", size: "h-9 w-32" },
  { side: "user", size: "h-14 w-52" },
  { side: "agent", size: "h-9 w-44" },
  { side: "user", size: "h-9 w-36" },
  { side: "user", size: "h-9 w-28" },
  { side: "agent", size: "h-14 w-60" },
  { side: "agent", size: "h-9 w-36" },
  { side: "user", size: "h-9 w-40" },
];

function ChatSkeleton() {
  return (
    <div className="pointer-events-none absolute inset-0 flex flex-col justify-end px-4 pb-4">
      {SKELETON_ROWS.map((row, i) => {
        const isUser = row.side === "user";
        const sameAsPrev = i > 0 && SKELETON_ROWS[i - 1].side === row.side;
        return (
          <div
            key={i}
            className={cn(
              "flex",
              isUser ? "justify-end" : "justify-start",
              i > 0 && (sameAsPrev ? "mt-1.5" : "mt-5"),
            )}
          >
            <div
              className={cn(
                "animate-pulse rounded-squircle-sm [corner-shape:squircle]",
                row.size,
                isUser
                  ? "bg-primary rounded-br-sm"
                  : "bg-secondary rounded-bl-sm",
              )}
            />
          </div>
        );
      })}
    </div>
  );
}

export function ChatMessageArea({
  scrollRef,
  loadMore,
  hasMore,
  loadingMore,
  fullscreen,
  navbarHeight,
  chatMessages,
  connected,
  historyLoaded,
  agentName,
  notAuthenticated,
  isTyping,
  isMobile,
}: ChatMessageAreaProps) {
  const decorated = useMemo(() => buildDecorated(chatMessages), [chatMessages]);
  const count = decorated.length;
  const lastAgentText = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      const event = chatMessages[i];
      if (event.type === "chat") return event.text;
    }
    return "";
  }, [chatMessages]);
  const parentRef = useRef<HTMLDivElement>(null);
  // Drives the scroll-to-bottom button: true while pinned near the latest message, false once
  // the user scrolls up. Recomputed on scroll and on content resize (see below).
  const [atBottom, setAtBottom] = useState(true);

  const getItemKey = useCallback(
    (index: number) => decorated[index].key,
    [decorated],
  );

  const estimateSize = useCallback(
    (index: number) =>
      decorated[index]?.event.type === "tool_start"
        ? ESTIMATED_TOOL_HEIGHT
        : ESTIMATED_MESSAGE_HEIGHT,
    [decorated],
  );

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => parentRef.current,
    estimateSize,
    getItemKey,
    // End-anchored chat scrolling: TanStack captures the visible keyed row before a data
    // change and re-pins it after — keeping scroll stable across prepends (load older),
    // streaming growth, and the show-tools toggle's mid-list inserts/removes.
    anchorTo: "end",
    followOnAppend: "smooth",
    scrollEndThreshold: AT_BOTTOM_THRESHOLD_PX,
    overscan: OVERSCAN_ROWS,
    // Apply row positions straight to the DOM instead of through a React re-render on every
    // scroll frame. Critical for smooth upward scrolling, where measuring newly-revealed rows
    // constantly nudges offsets — going through React there is what stutters.
    directDomUpdates: true,
  });

  useImperativeHandle(
    scrollRef,
    () => ({
      scrollToBottom: () => virtualizer.scrollToEnd({ behavior: "smooth" }),
    }),
    [virtualizer],
  );

  // Jump to the latest message when the first page of history arrives, and again whenever
  // the list resets to empty (agent switch / reconnect) and repopulates.
  const hadRowsRef = useRef(false);
  useLayoutEffect(() => {
    const hasRows = count > 0;
    if (hasRows && !hadRowsRef.current) virtualizer.scrollToEnd();
    hadRowsRef.current = hasRows;
  }, [count, virtualizer]);

  // Highest row index seen as of the last commit — read during render (holds the prior
  // value, since this effect hasn't fired yet) to tell a genuine append from a history
  // page landing or an unrelated re-render, then advanced after commit. Gated on
  // hadRowsRef so the first page of history never plays the entrance animation.
  const maxSeenIndexRef = useRef(-1);
  useLayoutEffect(() => {
    maxSeenIndexRef.current = count - 1;
  }, [count]);

  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    // Distance-from-end straight off the DOM rather than virtualizer.isAtEnd(): the latter
    // reads a measurement cache that can lag a row resize, and we recompute this from a
    // ResizeObserver too, so a single authoritative source keeps the two in agreement.
    const atEnd =
      el.scrollHeight - el.scrollTop - el.clientHeight <=
      AT_BOTTOM_THRESHOLD_PX;
    setAtBottom(atEnd);
    if (hasMore && !loadingMore && !atEnd && el.scrollTop < LOAD_OLDER_TOP_PX) {
      loadMore();
    }
  }, [hasMore, loadingMore, loadMore]);

  // "At bottom" depends on content height, not just scroll position: after the first paint the
  // virtualizer measures real row heights (vs. the estimates scrollToEnd used), which moves the
  // end without firing a scroll event. Recompute on every content resize so the button doesn't
  // get stuck showing when we're actually pinned to the latest message.
  useLayoutEffect(() => {
    const el = parentRef.current;
    const content = el?.firstElementChild;
    if (!el || !content) return;
    const ro = new ResizeObserver(() => {
      setAtBottom(
        el.scrollHeight - el.scrollTop - el.clientHeight <=
          AT_BOTTOM_THRESHOLD_PX,
      );
    });
    ro.observe(content);
    return () => ro.disconnect();
  }, []);

  const items = virtualizer.getVirtualItems();
  const topPad = fullscreen ? navbarHeight + 16 : 32;

  return (
    <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
      {/* persistent live region so screen readers hear agent replies as they arrive */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {lastAgentText}
      </span>
      {count === 0 &&
        (connected && !historyLoaded ? (
          <ChatSkeleton />
        ) : (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center pb-6">
            <span className="text-xs text-muted-foreground">
              {!connected
                ? "connecting..."
                : notAuthenticated
                  ? `${agentName} needs to sign in`
                  : `${agentName} is setting things up`}
            </span>
          </div>
        ))}
      <AnimatePresence>
        {loadingMore && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
            className={cn(
              "absolute left-1/2 -translate-x-1/2 z-10 pointer-events-none",
              fullscreen ? "top-[5rem]" : "top-10",
            )}
          >
            <span className="rounded-full border border-muted-foreground/20 bg-muted/80 backdrop-blur-sm px-3 py-1.5 text-xs text-muted-foreground">
              loading...
            </span>
          </motion.div>
        )}
      </AnimatePresence>
      <div
        ref={parentRef}
        onScroll={handleScroll}
        className="h-full overflow-y-auto overflow-x-hidden"
        style={{
          maskImage: `linear-gradient(to bottom, transparent, black ${fullscreen ? navbarHeight : 48}px, black calc(100% - 20px), transparent)`,
        }}
      >
        <div
          ref={virtualizer.containerRef}
          style={{ position: "relative", width: "100%" }}
        >
          {items.map((item) => {
            const row = decorated[item.index];
            const isLast = item.index === count - 1;
            const isNewAppend =
              hadRowsRef.current && item.index > maxSeenIndexRef.current;
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
                {row.isFirst && (
                  <div style={{ paddingTop: topPad }}>
                    {!hasMore && (
                      <div className="flex justify-center py-3">
                        <span className="text-[11px] text-muted-foreground">
                          beginning of conversation
                        </span>
                      </div>
                    )}
                  </div>
                )}
                <div className="flex flex-col px-4">
                  {row.showDayStamp && row.dayLabel && (
                    <div
                      className={cn(
                        "flex justify-center",
                        !row.isFirst && "mt-5",
                      )}
                    >
                      <span className="text-[11px] text-muted-foreground select-none">
                        {row.dayLabel}
                      </span>
                    </div>
                  )}
                  {isNewAppend ? (
                    <motion.div
                      initial={{ opacity: 0, y: 6, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={stepTransition.transition}
                    >
                      <ChatBubble
                        event={row.event}
                        className={row.gap}
                        fullscreen={fullscreen}
                        isMobile={isMobile}
                      />
                    </motion.div>
                  ) : (
                    <ChatBubble
                      event={row.event}
                      className={row.gap}
                      fullscreen={fullscreen}
                      isMobile={isMobile}
                    />
                  )}
                </div>
                {isLast && (
                  <div className="px-4 pb-4">
                    {isTyping && (
                      <div className="flex justify-start mt-2">
                        <div className="flex items-center gap-1 bg-secondary text-secondary-foreground rounded-2xl rounded-bl-sm px-3.5 py-2.5">
                          <span className="sr-only">typing...</span>
                          <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce motion-reduce:animate-none [animation-delay:0ms]" />
                          <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce motion-reduce:animate-none [animation-delay:150ms]" />
                          <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce motion-reduce:animate-none [animation-delay:300ms]" />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {count > 0 && (
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="Scroll to latest message"
          data-active={!atBottom}
          onClick={() => virtualizer.scrollToEnd({ behavior: "smooth" })}
          className={cn(
            "absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full shadow-sm transition-all duration-200",
            "data-[active=false]:pointer-events-none data-[active=false]:translate-y-full data-[active=false]:scale-95 data-[active=false]:opacity-0 data-[active=false]:duration-150 data-[active=false]:ease-[cubic-bezier(0.7,0,0.84,0)]",
            "data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100 data-[active=true]:ease-[cubic-bezier(0.23,1,0.32,1)]",
          )}
        >
          <ArrowDown />
        </Button>
      )}
    </CardContent>
  );
}
