import {
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  type RefObject,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AnimatePresence, motion } from "motion/react";
import { CardContent } from "@/components/ui/card";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { stepTransition } from "@/lib/motion";
import {
  BUBBLE_BODY_RADIUS,
  BUBBLE_TAIL_RADIUS,
  ChatBubble,
  type RetryHandler,
} from "../ChatBubble";
import { CHAT_CONTENT_WIDTH } from "../content-width";
import { buildDecorated } from "./virtual";

// First-paint estimate per row (actual heights are measured).
const ESTIMATED_MESSAGE_HEIGHT = 64;
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
  chatMessages: ChatMessage[];
  connected: boolean;
  historyLoaded: boolean;
  agentName: string;
  notAuthenticated: boolean;
  isTyping: boolean;
  isMobile: boolean;
  onRetry?: RetryHandler;
  // Space reserved at the end of the list so the last message clears the floating composer.
  bottomInset?: number;
  // Fires when pinned-to-latest flips; drives the parent's scroll-to-bottom button.
  onAtBottomChange: (atBottom: boolean) => void;
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

function ChatSkeleton({ bottomPad }: { bottomPad: number }) {
  return (
    <div
      className="pointer-events-none absolute inset-0 flex flex-col justify-end px-4"
      style={{ paddingBottom: bottomPad }}
    >
      {SKELETON_ROWS.map((row, i) => {
        const isUser = row.side === "user";
        const sameAsPrev = i > 0 && SKELETON_ROWS[i - 1]?.side === row.side;
        const isGroupEnd = SKELETON_ROWS[i + 1]?.side !== row.side;
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
                "animate-pulse",
                row.size,
                isUser ? "bg-primary" : "bg-secondary",
              )}
              style={{
                borderTopLeftRadius: BUBBLE_BODY_RADIUS,
                borderTopRightRadius: BUBBLE_BODY_RADIUS,
                borderBottomLeftRadius: BUBBLE_BODY_RADIUS,
                borderBottomRightRadius: BUBBLE_BODY_RADIUS,
                ...(isGroupEnd &&
                  isUser && { borderBottomRightRadius: BUBBLE_TAIL_RADIUS }),
                ...(isGroupEnd &&
                  !isUser && { borderBottomLeftRadius: BUBBLE_TAIL_RADIUS }),
              }}
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
  onRetry,
  bottomInset = 0,
  onAtBottomChange,
}: ChatMessageAreaProps) {
  // Desktop treatment (floating-composer inset, spacious gaps, sizes) applies to both the
  // fullscreen and split-panel chats; only mobile keeps the plain layout. The narrow centered
  // column is fullscreen-only, the split-panel chat fills its panel.
  const floating = !isMobile;
  const centered = Boolean(fullscreen) && !isMobile;
  const decorated = useMemo(
    () => buildDecorated(chatMessages, floating),
    [chatMessages, floating],
  );
  const count = decorated.length;
  const lastAgentText = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      const event = chatMessages[i];
      if (event?.type === "chat") return event.text;
    }
    return "";
  }, [chatMessages]);
  const parentRef = useRef<HTMLDivElement>(null);
  // True while pinned near the latest message, false once the user scrolls up.
  // Recomputed on scroll and on content resize (see below); the parent renders
  // the scroll-to-bottom button off it, notified only on change.
  const atBottomRef = useRef(true);
  const setAtBottom = useCallback(
    (pinned: boolean) => {
      if (atBottomRef.current === pinned) return;
      atBottomRef.current = pinned;
      onAtBottomChange(pinned);
    },
    [onAtBottomChange],
  );

  const getItemKey = useCallback(
    (index: number) => decorated[index]?.key ?? String(index),
    [decorated],
  );

  const estimateSize = useCallback(() => ESTIMATED_MESSAGE_HEIGHT, []);

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => parentRef.current,
    estimateSize,
    getItemKey,
    // End-anchored chat scrolling: TanStack captures the visible keyed row before a data
    // change and re-pins it after — keeping scroll stable across prepends (load older)
    // and streaming growth.
    anchorTo: "end",
    followOnAppend: "smooth",
    scrollEndThreshold: AT_BOTTOM_THRESHOLD_PX,
    paddingEnd: bottomInset,
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

  // The composer inset lands after the initial end-jump (its ResizeObserver is async) and
  // changes while a multi-line draft grows; the virtualizer never re-anchors on a padding
  // change, so while pinned we re-pin ourselves.
  useLayoutEffect(() => {
    if (atBottomRef.current) virtualizer.scrollToEnd();
  }, [bottomInset, virtualizer]);

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
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      const pinned = dist <= AT_BOTTOM_THRESHOLD_PX;
      setAtBottom(pinned);
      // Repay any shortfall a smooth follow left behind: the virtualizer skips
      // its own end re-pin while a smooth scroll is in flight, so a row measured
      // mid-animation lands short and would otherwise stay short.
      if (pinned && dist > 1) virtualizer.scrollToEnd();
    });
    ro.observe(content);
    return () => ro.disconnect();
  }, [setAtBottom, virtualizer]);

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
          // The extra 16px mirrors the real list's trailing pb-4 (the typing
          // indicator slot after the last row), so the skeleton's last bubble
          // sits exactly where a real last bubble does.
          <ChatSkeleton bottomPad={bottomInset + 16} />
        ) : (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center"
            style={{ paddingBottom: bottomInset + 24 }}
          >
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
        className={cn(
          "h-full overflow-y-auto overflow-x-hidden",
          // Reserve the scrollbar gutter on both sides so the centered message column
          // shares the same center as the (scrollbar-free) floating composer.
          floating && "[scrollbar-gutter:stable_both-edges]",
        )}
        // One mask owns both fades. Fullscreen's top approximates the old
        // stacked card+list pair: near-invisible within the navbar's height,
        // then a long dissolve (3.5x/1.75x the navbar) so bubbles evaporate
        // before reaching it. The bottom stop fades behind the composer.
        style={{
          maskImage: `linear-gradient(to bottom, ${
            fullscreen
              ? `rgb(0 0 0 / 0) 0px, rgb(0 0 0 / 0.25) ${String(navbarHeight)}px, black ${String(Math.round(navbarHeight * (isMobile ? 1.75 : 3.5)))}px`
              : "transparent, black 48px"
          }, black calc(100% - ${String(bottomInset)}px), transparent)`,
        }}
      >
        <div
          ref={virtualizer.containerRef}
          style={{ position: "relative", width: "100%" }}
        >
          {items.map((item) => {
            const row = decorated[item.index];
            if (!row) return null;
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
                <div className={cn(centered && CHAT_CONTENT_WIDTH)}>
                  {row.isFirst && (
                    <div style={{ paddingTop: topPad }}>
                      {!hasMore && (
                        <div className="flex justify-center py-3">
                          <span className="text-[11px] text-muted-foreground/40">
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
                        <span
                          className={cn(
                            "text-muted-foreground/60 select-none",
                            floating ? "text-sm" : "text-[11px]",
                          )}
                        >
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
                          isMobile={isMobile}
                          hasTail={row.isGroupEnd}
                          onRetry={onRetry}
                        />
                      </motion.div>
                    ) : (
                      <ChatBubble
                        event={row.event}
                        className={row.gap}
                        isMobile={isMobile}
                        hasTail={row.isGroupEnd}
                        onRetry={onRetry}
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
              </div>
            );
          })}
        </div>
      </div>
    </CardContent>
  );
}
