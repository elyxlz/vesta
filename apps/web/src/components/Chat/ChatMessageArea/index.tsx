import {
  memo,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  type RefObject,
} from "react";
import { AnimatePresence, motion } from "motion/react";
import { CardContent } from "@/components/ui/card";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { stepTransition } from "@/lib/motion";
import { bubbleRadiusStyle } from "../bubble-radius";
import { ChatBubble, type RetryHandler } from "../ChatBubble";
import { CHAT_CONTENT_WIDTH } from "../content-width";
import { buildDecorated, lastSeenIndex, type DecoratedRow } from "./rows";
import { useChatScroll } from "./use-chat-scroll";

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
  // A tall draft's extra composer height beyond the baseline inset. It extends the scroll
  // range so covered bubbles stay reachable, without moving the pinned viewport.
  bottomOverhang?: number;
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
              style={bubbleRadiusStyle(isUser, isGroupEnd)}
            />
          </div>
        );
      })}
    </div>
  );
}

// One mask owns both fades. Fullscreen's top approximates the old stacked card+list
// pair: near-invisible within the navbar's height, then a long dissolve (3.5x/1.75x
// the navbar) so bubbles evaporate before reaching it. The bottom stop fades behind
// the composer.
function scrollerMask(
  fullscreen: boolean,
  isMobile: boolean,
  navbarHeight: number,
  bottomInset: number,
): string {
  const top = fullscreen
    ? `rgb(0 0 0 / 0) 0px, rgb(0 0 0 / 0.25) ${String(navbarHeight)}px, black ${String(Math.round(navbarHeight * (isMobile ? 1.75 : 3.5)))}px`
    : "transparent, black 48px";
  return `linear-gradient(to bottom, ${top}, black calc(100% - ${String(bottomInset)}px), transparent)`;
}

function ChatEmptyState({
  connected,
  historyLoaded,
  notAuthenticated,
  agentName,
  bottomInset,
}: {
  connected: boolean;
  historyLoaded: boolean;
  notAuthenticated: boolean;
  agentName: string;
  bottomInset: number;
}) {
  if (connected && !historyLoaded) {
    // The extra 16px mirrors the real list's trailing pb-4 (the typing
    // indicator slot after the last row), so the skeleton's last bubble
    // sits exactly where a real last bubble does.
    return <ChatSkeleton bottomPad={bottomInset + 16} />;
  }
  return (
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
  );
}

function MessageRow({
  row,
  index,
  isMobile,
  isNewAppend,
  onRetry,
}: {
  row: DecoratedRow;
  index: number;
  isMobile: boolean;
  isNewAppend: boolean;
  onRetry?: RetryHandler;
}) {
  const bubble = (
    <ChatBubble
      event={row.event}
      className={row.gap}
      isMobile={isMobile}
      hasTail={row.isGroupEnd}
      onRetry={onRetry}
    />
  );
  return (
    <>
      {row.showDayStamp && row.dayLabel && (
        <div className={cn("flex justify-center", index > 0 && "mt-5")}>
          <span
            className={cn(
              "text-muted-foreground/60 select-none",
              isMobile ? "text-[11px]" : "text-sm",
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
          {bubble}
        </motion.div>
      ) : (
        bubble
      )}
    </>
  );
}

// The index the previous commit's last row now sits at — read during render (the effect
// hasn't advanced the ref yet), so rows past it are genuine appends and animate in,
// while a history page landing above (which shifts indices) never does.
function useAppendBoundary(decorated: DecoratedRow[]): number {
  const prevLastKeyRef = useRef<string | null>(null);
  const prevLastIndex = lastSeenIndex(decorated, prevLastKeyRef.current);
  useLayoutEffect(() => {
    prevLastKeyRef.current = decorated[decorated.length - 1]?.key ?? null;
  }, [decorated]);
  return prevLastIndex;
}

// Every fetched row stays mounted in a plain scroller: each message parses its markdown
// once, ever, and scrolling moves static DOM (the same choice the Console makes, for the
// same reason — no windowing, no size estimates, no remount cost). History paging bounds
// the DOM, so long conversations stay cheap. memo keeps the parent's per-keystroke
// composer re-renders from re-invoking every mounted row.
export const ChatMessageArea = memo(function ChatMessageArea({
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
  bottomOverhang = 0,
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

  const { handleScroll, scrollToBottom, waitingForOlder } = useChatScroll({
    parentRef,
    count,
    firstKey: decorated[0]?.key ?? null,
    bottomInset,
    bottomOverhang,
    hasMore,
    loadingMore,
    loadMore,
    onAtBottomChange,
  });

  const prevLastIndex = useAppendBoundary(decorated);

  useImperativeHandle(scrollRef, () => ({ scrollToBottom }), [scrollToBottom]);

  const topPad = fullscreen ? navbarHeight + 16 : 32;

  return (
    <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
      {/* persistent live region so screen readers hear agent replies as they arrive */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {lastAgentText}
      </span>
      {count === 0 && (
        <ChatEmptyState
          connected={connected}
          historyLoaded={historyLoaded}
          notAuthenticated={notAuthenticated}
          agentName={agentName}
          bottomInset={bottomInset}
        />
      )}
      <AnimatePresence>
        {waitingForOlder && (
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
            <span className="rounded-full border border-border bg-popover px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
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
        // The prepend restore owns anchoring; the browser's native scroll
        // anchoring would compensate the same prepend a second time.
        style={{
          overflowAnchor: "none",
          maskImage: scrollerMask(
            Boolean(fullscreen),
            isMobile,
            navbarHeight,
            bottomInset,
          ),
        }}
      >
        <div
          className={cn(centered && CHAT_CONTENT_WIDTH)}
          style={{ paddingBottom: bottomInset }}
        >
          <div style={{ paddingTop: topPad }}>
            {count > 0 && !hasMore && (
              <div className="flex justify-center py-3">
                <span className="text-[11px] text-muted-foreground/40">
                  beginning of conversation
                </span>
              </div>
            )}
          </div>
          <div className="flex flex-col px-4">
            {decorated.map((row, index) => (
              <MessageRow
                key={row.key}
                row={row}
                index={index}
                isMobile={isMobile}
                isNewAppend={prevLastIndex >= 0 && index > prevLastIndex}
                onRetry={onRetry}
              />
            ))}
          </div>
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
        </div>
        {/* The draft's overhang sits outside the resize-observed content div, so a growing
            draft extends the scroll range without ever triggering the pinned re-pin. */}
        <div style={{ height: bottomOverhang }} />
      </div>
    </CardContent>
  );
});
