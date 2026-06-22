import { useMemo, type RefObject } from "react";
import { Virtuoso, type Components, type VirtuosoHandle } from "react-virtuoso";
import { AnimatePresence, motion } from "motion/react";
import { CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { createScroller } from "@/lib/virtuoso";
import { ChatBubble } from "../ChatBubble";
import {
  buildDecorated,
  useStableFirstItemIndex,
  type DecoratedRow,
} from "./virtual";

interface ChatListContext {
  isTyping: boolean;
  hasMore: boolean;
  hasMessages: boolean;
  fullscreen?: boolean;
  navbarHeight: number;
  isMobile: boolean;
}

interface ChatMessageAreaProps {
  virtuosoRef: RefObject<VirtuosoHandle | null>;
  onStartReached: () => void;
  onAtTopStateChange: (atTop: boolean) => void;
  onAtBottomStateChange: (atBottom: boolean) => void;
  fullscreen?: boolean;
  navbarHeight: number;
  loadingMore: boolean;
  hasMore: boolean;
  chatMessages: VestaEvent[];
  connected: boolean;
  historyLoaded: boolean;
  agentName: string;
  notAuthenticated: boolean;
  isTyping: boolean;
  isMobile: boolean;
}

const Scroller = createScroller<DecoratedRow, ChatListContext>((context) => {
  const navbarHeight = context?.navbarHeight ?? 0;
  return {
    style: {
      maskImage: `linear-gradient(to bottom, transparent, black ${context?.fullscreen ? navbarHeight : 48}px, black calc(100% - 20px), transparent)`,
    },
  };
});

function Header({ context }: { context?: ChatListContext }) {
  if (!context) return null;
  const paddingTop = context.fullscreen
    ? `calc(${context.navbarHeight}px + 1rem)`
    : 32;
  return (
    <div style={{ paddingTop }}>
      {!context.hasMore && context.hasMessages && (
        <div className="flex justify-center py-3">
          <span className="text-[11px] text-muted-foreground/40">
            beginning of conversation
          </span>
        </div>
      )}
    </div>
  );
}

function Footer({ context }: { context?: ChatListContext }) {
  return (
    <div className="px-4 pb-4">
      {context?.isTyping && (
        <div className="flex justify-start mt-2">
          <div className="flex items-center gap-1 bg-secondary text-secondary-foreground rounded-2xl rounded-bl-sm px-3.5 py-2.5">
            <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:0ms]" />
            <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:150ms]" />
            <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:300ms]" />
          </div>
        </div>
      )}
    </div>
  );
}

const components: Components<DecoratedRow, ChatListContext> = {
  Scroller,
  Header,
  Footer,
};

// Placeholder bubbles shown while the first page of history is in flight, so a slow
// load reads as a conversation arriving rather than an empty/"needs to sign in" state.
const SKELETON_ROWS: { align: string; size: string; tint: string }[] = [
  { align: "justify-start", size: "h-8 w-44", tint: "bg-muted" },
  { align: "justify-end", size: "h-8 w-28", tint: "bg-primary/15" },
  { align: "justify-start", size: "h-12 w-60", tint: "bg-muted" },
  { align: "justify-end", size: "h-8 w-36", tint: "bg-primary/15" },
  { align: "justify-start", size: "h-8 w-32", tint: "bg-muted" },
];

function ChatSkeleton({
  fullscreen,
  navbarHeight,
}: {
  fullscreen?: boolean;
  navbarHeight: number;
}) {
  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col justify-end gap-3 px-4 pb-4"
      style={{ paddingTop: fullscreen ? navbarHeight + 16 : 32 }}
    >
      {SKELETON_ROWS.map((row, i) => (
        <div key={i} className={cn("flex", row.align)}>
          <Skeleton
            className={cn(
              "rounded-squircle-sm [corner-shape:squircle]",
              row.size,
              row.tint,
            )}
          />
        </div>
      ))}
    </div>
  );
}

export function ChatMessageArea({
  virtuosoRef,
  onStartReached,
  onAtTopStateChange,
  onAtBottomStateChange,
  fullscreen,
  navbarHeight,
  loadingMore,
  hasMore,
  chatMessages,
  connected,
  historyLoaded,
  agentName,
  notAuthenticated,
  isTyping,
  isMobile,
}: ChatMessageAreaProps) {
  const decorated = useMemo(() => buildDecorated(chatMessages), [chatMessages]);
  const firstItemIndex = useStableFirstItemIndex(decorated);

  const context = useMemo<ChatListContext>(
    () => ({
      isTyping,
      hasMore,
      hasMessages: decorated.length > 0,
      fullscreen,
      navbarHeight,
      isMobile,
    }),
    [isTyping, hasMore, decorated.length, fullscreen, navbarHeight, isMobile],
  );

  return (
    <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
      {decorated.length === 0 &&
        (connected && !historyLoaded ? (
          <ChatSkeleton fullscreen={fullscreen} navbarHeight={navbarHeight} />
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
      <Virtuoso<DecoratedRow, ChatListContext>
        ref={virtuosoRef}
        className="h-full"
        data={decorated}
        context={context}
        components={components}
        firstItemIndex={firstItemIndex}
        computeItemKey={(_index, row) => row.key}
        alignToBottom
        followOutput={(atBottom) => (atBottom ? "smooth" : false)}
        initialTopMostItemIndex={{ index: "LAST", align: "end" }}
        startReached={onStartReached}
        atTopStateChange={onAtTopStateChange}
        atBottomStateChange={onAtBottomStateChange}
        atBottomThreshold={48}
        increaseViewportBy={{ top: 600, bottom: 200 }}
        itemContent={(_index, row, ctx) => (
          <div className="flex flex-col px-4">
            {row.showDayStamp && row.dayLabel && (
              <div
                className={cn("flex justify-center", !row.isFirst && "mt-5")}
              >
                <span className="text-[11px] text-muted-foreground/60 select-none">
                  {row.dayLabel}
                </span>
              </div>
            )}
            <ChatBubble
              event={row.event}
              className={row.gap}
              fullscreen={ctx.fullscreen}
              isMobile={ctx.isMobile}
            />
          </div>
        )}
      />
    </CardContent>
  );
}
