import type { RefObject } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CardContent } from "@/components/ui/card";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChatBubble } from "../ChatBubble";

interface ChatMessageAreaProps {
  scrollRef: RefObject<HTMLDivElement | null>;
  bottomRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  fullscreen?: boolean;
  navbarHeight: number;
  loadingMore: boolean;
  hasMore: boolean;
  chatMessages: VestaEvent[];
  connected: boolean;
  agentName: string;
  isTyping: boolean;
}

export function ChatMessageArea({
  scrollRef,
  bottomRef,
  onScroll,
  fullscreen,
  navbarHeight,
  loadingMore,
  hasMore,
  chatMessages,
  connected,
  agentName,
  isTyping,
}: ChatMessageAreaProps) {
  return (
    <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
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
        ref={scrollRef}
        onScroll={onScroll}
        className="h-full min-h-0 overflow-y-auto flex flex-col-reverse pb-4 px-4"
        style={{
          paddingTop: fullscreen ? `calc(${navbarHeight}px + 1rem)` : 32,
          maskImage: `linear-gradient(to bottom, transparent, black ${fullscreen ? navbarHeight : 48}px, black calc(100% - 20px), transparent)`,
        }}
      >
        <div ref={bottomRef} className="h-px shrink-0" />
        {isTyping && (
          <div className="flex justify-start mt-2">
            <div className="flex items-center gap-1 bg-secondary text-secondary-foreground rounded-2xl rounded-bl-sm px-3.5 py-2.5">
              <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:0ms]" />
              <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:150ms]" />
              <span className="size-1.5 rounded-full bg-secondary-foreground/45 animate-bounce [animation-delay:300ms]" />
            </div>
          </div>
        )}
        <div>
          {chatMessages.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-2">
              <span className="text-xs text-muted-foreground">
                {connected
                  ? `${agentName} is setting things up`
                  : "connecting..."}
              </span>
            </div>
          ) : (
            <div className="flex flex-col">
              {(() => {
                let lastDayKey: string | null = null;
                return chatMessages.map((msg, i) => {
                  const prev = chatMessages[i - 1];
                  const dayKey = calendarDayKey(msg.ts);
                  const showDayStamp = Boolean(
                    dayKey && (lastDayKey === null || dayKey !== lastDayKey),
                  );
                  if (dayKey) lastDayKey = dayKey;
                  const isTool = msg.type === "tool_start";
                  const prevIsTool = prev?.type === "tool_start";
                  const gap = showDayStamp
                    ? "mt-2"
                    : i === 0
                      ? ""
                      : isTool && prevIsTool
                        ? "mt-1"
                        : isTool || prevIsTool
                          ? "mt-2"
                          : prev && prev.type === msg.type
                            ? "mt-1.5"
                            : "mt-5";
                  const dayLabel =
                    showDayStamp && msg.ts
                      ? formatChatDayStampLabel(msg.ts)
                      : "";
                  return (
                    <div
                      key={msg.ts ? `${msg.ts}-${msg.type}` : `idx-${i}`}
                      className="flex flex-col"
                    >
                      {showDayStamp && dayLabel && (
                        <div
                          className={cn(
                            "flex justify-center",
                            i > 0 ? "mt-5" : "",
                          )}
                        >
                          <span className="text-[11px] text-muted-foreground/60 select-none">
                            {dayLabel}
                          </span>
                        </div>
                      )}
                      <ChatBubble event={msg} className={gap} />
                    </div>
                  );
                });
              })()}
            </div>
          )}
        </div>
        {!hasMore && chatMessages.length > 0 && (
          <div className="flex justify-center py-3">
            <span className="text-[11px] text-muted-foreground/40">
              beginning of conversation
            </span>
          </div>
        )}
      </div>
    </CardContent>
  );
}
