import { memo } from "react";
import { bubbleRadiusStyle } from "../bubble-radius";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import { formatResetTime } from "@vesta/core";
import type { ChatAttachment, InputMethod } from "@vesta/core";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AttachmentContent, type OpenViewerRequest } from "./AttachmentContent";

export type RetryHandler = (
  intentId: string,
  text: string,
  inputMethod?: InputMethod,
  attachments?: ChatAttachment[],
) => void;

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
  agentName,
  onOpenAttachment,
}: {
  event: ChatMessage;
  className?: string;
  isMobile: boolean;
  hasTail?: boolean;
  onRetry?: RetryHandler;
  agentName?: string;
  onOpenAttachment?: (request: OpenViewerRequest) => void;
}) {
  // Desktop chats read at 16px body / 14px meta; mobile keeps its smaller sizes.
  const large = !isMobile;
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

  const ts = formatBubbleTime(event.ts);

  // A send whose POST failed (503 retryable) or errored: a subtle "not sent" line with tap-to-retry,
  // re-posting the same intent id. Delivery truth is still the echo, which clears send_state.
  if (
    event.type === "user" &&
    event.intent_id != null &&
    (event.send_state === "retry" || event.send_state === "failed")
  ) {
    const intentId = event.intent_id;
    const { text, input_method, attachments } = event;
    return (
      <div className={className}>
        <MessageBubble
          isUser
          text={text}
          ts={ts}
          large={large}
          hasTail={hasTail}
          attachments={attachments}
          agentName={agentName}
          onOpenAttachment={onOpenAttachment}
        />
        <div className="mt-0.5 flex justify-end pr-1">
          <button
            type="button"
            onClick={() => {
              onRetry?.(intentId, text, input_method, attachments);
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
      ts={ts}
      className={className}
      large={large}
      hasTail={hasTail}
      attachments={event.attachments}
      agentName={agentName}
      onOpenAttachment={onOpenAttachment}
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
  attachments,
  agentName,
  onOpenAttachment,
}: {
  isUser: boolean;
  text: string;
  ts: string;
  className?: string;
  // Desktop fullscreen: 16px body text (overrides the ui bubble's text-sm default).
  large: boolean;
  // Only the last bubble of a group carries the tighter tail corner.
  hasTail: boolean;
  attachments?: ChatAttachment[];
  agentName?: string;
  onOpenAttachment?: (request: OpenViewerRequest) => void;
}) {
  // Attachments need the agent name to build their URLs; a caller that omits it (the Debug
  // stream) renders the caption alone.
  const blocks =
    agentName !== undefined &&
    attachments !== undefined &&
    attachments.length > 0
      ? { agentName, attachments }
      : null;
  return (
    <Message align={isUser ? "end" : "start"} className={className}>
      <Bubble
        variant={isUser ? "default" : "secondary"}
        align={isUser ? "end" : "start"}
        className="max-w-[85%]"
      >
        <BubbleContent
          className={cn("flex items-end px-3.5 py-1.5", large && "text-base")}
          // Pill bubble; the last bubble of a group gets one tighter "tail"
          // corner for the conversation look.
          style={bubbleRadiusStyle(isUser, hasTail)}
        >
          {/* Block flow (not flex) so adjacent markdown paragraphs keep their collapsed margins. */}
          <div className="min-w-0 break-words">
            {blocks && (
              <div className={cn("flex flex-col gap-2.5 py-1", text && "mb-1")}>
                {blocks.attachments.map((attachment) => (
                  <AttachmentContent
                    key={attachment.id}
                    agent={blocks.agentName}
                    attachment={attachment}
                    onOpen={onOpenAttachment}
                  />
                ))}
              </div>
            )}
            {text && <Markdown>{text}</Markdown>}
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
