import { memo } from "react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import type { InputMethod } from "@vesta/core";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ToolCallLabel } from "../ToolCallLabel";

export type RetryHandler = (
  intentId: string,
  text: string,
  inputMethod?: InputMethod,
) => void;

// Coarse relative countdown to a rate-limit reset (unix seconds); minutes/hours/days is
// plenty of precision for "come back later" copy.
function formatResetTime(resetsAt: number): string {
  const minutes = Math.round((resetsAt * 1000 - Date.now()) / 60_000);
  if (minutes <= 1) return "in a minute";
  if (minutes < 60) return `in ${String(minutes)}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${String(hours)}h`;
  return `in ${String(Math.round(hours / 24))}d`;
}

function formatBubbleTime(ts: string | undefined): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function statusLineText(
  event: Extract<ChatMessage, { type: "error" | "rate_limited" }>,
): string {
  if (event.type === "error")
    return "hit a snag, this may not have gone through";
  return event.resets_at
    ? `rate limited, back ${formatResetTime(event.resets_at)}`
    : "rate limited, retrying later";
}

export const ChatBubble = memo(function ChatBubble({
  event,
  className,
  fullscreen,
  isMobile,
  onRetry,
}: {
  event: ChatMessage;
  className?: string;
  fullscreen?: boolean;
  isMobile: boolean;
  onRetry?: RetryHandler;
}) {
  if (event.type === "status") return null;

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
    return (
      <div className={cn("flex justify-center", className)}>
        <span className="text-[11px] text-muted-foreground/60 select-none">
          {statusLineText(event)}
        </span>
      </div>
    );
  }

  if (event.type !== "user" && event.type !== "chat") return null;

  // A send whose POST failed (503 retryable) or errored: a subtle "not sent" line with tap-to-retry,
  // re-posting the same intent id. Delivery truth is still the echo, which clears send_state.
  if (
    event.type === "user" &&
    event.intent_id != null &&
    (event.send_state === "retry" || event.send_state === "failed")
  ) {
    const intentId = event.intent_id;
    const { text, input_method } = event;
    return (
      <div className={className}>
        <MessageBubble
          isUser
          text={text}
          ts={formatBubbleTime(event.ts)}
          mobileCard={Boolean(fullscreen && isMobile)}
        />
        <div className="mt-0.5 flex justify-end pr-1">
          <button
            type="button"
            onClick={() => {
              onRetry?.(intentId, text, input_method);
            }}
            className="text-[10px] text-destructive/70 transition-colors select-none hover:text-destructive"
          >
            not sent · tap to retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <MessageBubble
      isUser={event.type === "user"}
      text={event.text}
      ts={formatBubbleTime(event.ts)}
      className={className}
      mobileCard={Boolean(fullscreen && isMobile)}
    />
  );
});

function MessageBubble({
  isUser,
  text,
  ts,
  className,
  mobileCard,
}: {
  isUser: boolean;
  text: string;
  ts: string;
  className?: string;
  // Mobile fullscreen lifts the agent bubble onto a card surface with a ring/shadow; the
  // bg override goes through the same `*:data-[slot=bubble-content]` channel the variant uses
  // so twMerge drops the variant's bg-secondary cleanly.
  mobileCard: boolean;
}) {
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
}
