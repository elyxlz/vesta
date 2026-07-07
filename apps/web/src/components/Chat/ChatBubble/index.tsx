import { memo } from "react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ToolCallLabel } from "../ToolCallLabel";

export const ChatBubble = memo(function ChatBubble({
  event,
  className,
  fullscreen,
  isMobile,
}: {
  event: VestaEvent;
  className?: string;
  fullscreen?: boolean;
  isMobile: boolean;
}) {
  if (event.type === "status") return null;

  const ts = event.ts
    ? new Date(event.ts).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "";

  if (event.type === "tool_start") {
    return (
      <ToolCallLabel
        tool={event.tool}
        input={event.input}
        className={className}
      />
    );
  }

  if (event.type !== "user" && event.type !== "chat") return null;

  const isUser = event.type === "user";
  const text = event.text;
  // Mobile fullscreen lifts the agent bubble onto a card surface with a ring/shadow; the
  // bg override goes through the same `*:data-[slot=bubble-content]` channel the variant uses
  // so twMerge drops the variant's bg-secondary cleanly.
  const mobileCard = fullscreen && isMobile;

  return (
    <Message align={isUser ? "end" : "start"} className={className}>
      <Bubble
        variant={isUser ? "default" : "secondary"}
        align={isUser ? "end" : "start"}
        className={cn(
          "max-w-[85%]",
          !isUser && mobileCard && "*:data-[slot=bubble-content]:bg-card",
        )}
      >
        <BubbleContent
          className={cn(
            "flex items-end rounded-squircle-sm [corner-shape:squircle] px-3 py-1.5",
            isUser ? "rounded-br-sm" : "rounded-bl-sm",
            mobileCard &&
              "shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10",
          )}
        >
          <div className="min-w-0 break-words">
            <Markdown>{text}</Markdown>
          </div>
          {ts && (
            <span
              className={cn(
                "shrink-0 ml-auto pl-2 text-[10px] leading-relaxed select-none whitespace-nowrap",
                isUser
                  ? "text-primary-foreground/50"
                  : "text-muted-foreground/50",
              )}
            >
              {ts}
            </span>
          )}
        </BubbleContent>
      </Bubble>
    </Message>
  );
});
