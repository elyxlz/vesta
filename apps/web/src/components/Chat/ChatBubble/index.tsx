import { memo } from "react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ToolCallLabel } from "../ToolCallLabel";

// Coarse relative countdown to a rate-limit reset (unix seconds); minutes/hours/days is
// plenty of precision for "come back later" copy.
function formatResetTime(resetsAt: number): string {
  const minutes = Math.round((resetsAt * 1000 - Date.now()) / 60_000);
  if (minutes <= 1) return "in a minute";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

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

  if (event.type === "error" || event.type === "rate_limited") {
    const text =
      event.type === "rate_limited"
        ? event.resets_at
          ? `rate limited, back ${formatResetTime(event.resets_at)}`
          : "rate limited, retrying later"
        : "hit a snag, this may not have gone through";
    return (
      <div className={cn("flex justify-center", className)}>
        <span className="text-[11px] text-muted-foreground/60 select-none">
          {text}
        </span>
      </div>
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
                isUser ? "text-primary-foreground/90" : "text-muted-foreground",
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
