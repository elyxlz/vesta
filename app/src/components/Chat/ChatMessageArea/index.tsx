import type { RefObject } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CardContent } from "@/components/ui/card";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChatBubble } from "../ChatBubble";

interface ChatMessageAreaProps {
  scrollRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  fullscreen?: boolean;
  navbarHeight: number;
  hasNewMessage: boolean;
  onScrollToBottom: () => void;
  loadingMore: boolean;
  hasMore: boolean;
  chatMessages: VestaEvent[];
  connected: boolean;
  agentName: string;
}

export function ChatMessageArea({
  scrollRef,
  onScroll,
  fullscreen,
  navbarHeight,
  hasNewMessage,
  onScrollToBottom,
  loadingMore,
  hasMore,
  chatMessages,
  connected,
  agentName,
}: ChatMessageAreaProps) {
  return (
    <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
      <AnimatePresence>
        {hasNewMessage && (
          <motion.button
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18 }}
            onClick={onScrollToBottom}
            className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-primary cursor-pointer hover:bg-primary/10 transition-colors"
          >
            new message
          </motion.button>
        )}
      </AnimatePresence>
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
        className={cn(
          "h-full min-h-0 overflow-y-auto flex flex-col-reverse pb-4 px-4",
        )}
        style={{
          paddingTop: fullscreen
            ? `calc(${navbarHeight}px + 1rem)`
            : 32,
          maskImage: `linear-gradient(to bottom, transparent, black ${fullscreen ? navbarHeight * 2 : 48}px, black calc(100% - 20px), transparent)`,
        }}
      >
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
              {chatMessages.map((msg, i) => {
                const prev = chatMessages[i - 1];
                const isTool = msg.type === "tool_start";
                const prevIsTool = prev?.type === "tool_start";
                const gap =
                  i === 0
                    ? ""
                    : isTool && prevIsTool
                      ? "mt-1"
                      : isTool || prevIsTool
                        ? "mt-2"
                        : prev && prev.type === msg.type
                          ? "mt-1.5"
                          : "mt-5";
                return <ChatBubble key={msg.ts ? `${msg.ts}-${msg.type}` : `idx-${i}`} event={msg} className={gap} />;
              })}
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
