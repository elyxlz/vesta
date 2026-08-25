import { memo } from "react";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import type { InputMethod } from "@vesta/core";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

export type RetryHandler = (
  intentId: string,
  text: string,
  inputMethod?: InputMethod,
) => void;

// Bubble corner radii (px). The body radius is large but FINITE, not 9999: a pill-corner
// shares each edge with the tail, and CSS clamps a whole edge's radii proportionally, which
// crushes the tail to ~0. A finite body keeps the pill look while letting the tail show.
export const BUBBLE_BODY_RADIUS = 20;
// The one tail corner kept tighter than the body so the bubble reads as a chat bubble.
export const BUBBLE_TAIL_RADIUS = 6;

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
  isMobile,
  hasTail = true,
  onRetry,
}: {
  event: ChatMessage;
  className?: string;
  isMobile: boolean;
  hasTail?: boolean;
  onRetry?: RetryHandler;
}) {
  // Desktop chats read at 16px body / 14px meta; mobile keeps its smaller sizes.
  const large = !isMobile;
  const ts = formatBubbleTime(event.ts);
  if (event.type === "status") return null;

  if (event.type === "error" || event.type === "rate_limited") {
    return (
      <div className={cn("flex justify-center", className)}>
        <span
          className={cn(
            "text-muted-foreground/60 select-none",
            large ? "text-sm" : "text-[11px]",
          )}
        >
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
          ts={ts}
          large={large}
          hasTail={hasTail}
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
      large={large}
      hasTail={hasTail}
    />
  );
});

function MessageBubble({
  isUser,
  text,
  ts,
  className,
  large,
  hasTail,
}: {
  isUser: boolean;
  text: string;
  ts: string;
  className?: string;
  // Desktop fullscreen: 16px body text (overrides the ui bubble's text-sm default).
  large: boolean;
  // Only the last bubble of a group carries the tighter tail corner.
  hasTail: boolean;
}) {
  return (
    <Message align={isUser ? "end" : "start"} className={className}>
      <Bubble
        variant={isUser ? "default" : "secondary"}
        align={isUser ? "end" : "start"}
        className="max-w-[85%]"
      >
        <BubbleContent
          className={cn("flex items-end px-3.5 py-1.5", large && "text-base")}
          // Pill bubble; the last bubble of a group gets one tighter "tail" corner for the
          // conversation look. All four corners as longhands (no `borderRadius` shorthand) so
          // React never drops the per-corner override, and inline so it beats the ui base radius.
          style={{
            borderTopLeftRadius: BUBBLE_BODY_RADIUS,
            borderTopRightRadius: BUBBLE_BODY_RADIUS,
            borderBottomLeftRadius: BUBBLE_BODY_RADIUS,
            borderBottomRightRadius: BUBBLE_BODY_RADIUS,
            ...(hasTail &&
              isUser && { borderBottomRightRadius: BUBBLE_TAIL_RADIUS }),
            ...(hasTail &&
              !isUser && { borderBottomLeftRadius: BUBBLE_TAIL_RADIUS }),
          }}
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
