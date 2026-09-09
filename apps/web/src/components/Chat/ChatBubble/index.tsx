import { memo } from "react";
import { bubbleRadiusStyle } from "../bubble-radius";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message } from "@/components/ui/message";
import { Markdown } from "@/lib/markdown";
import type { ChatAttachment, InputMethod, ChatMessage } from "@vesta/core";
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

export const ChatBubble = memo(function ChatBubble({
  event,
  className,
  isMobile,
  hasTail = true,
  sender = null,
  onRetry,
  onOpenAttachment,
}: {
  event: ChatMessage;
  className?: string;
  isMobile: boolean;
  hasTail?: boolean;
  // Who wrote this, printed above the bubble. Null unless the room has several agents and this
  // bubble opens one of their groups: a conversation with one agent needs no name on it.
  sender?: string | null;
  onRetry?: RetryHandler;
  onOpenAttachment?: (request: OpenViewerRequest) => void;
}) {
  // Desktop chats read at 16px body / 14px meta; mobile keeps its smaller sizes.
  const large = !isMobile;
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
          sender={sender}
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
      sender={sender}
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
  sender,
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
  sender?: string | null;
  onOpenAttachment?: (request: OpenViewerRequest) => void;
}) {
  const blocks = attachments && attachments.length > 0 ? attachments : null;
  return (
    <div className={className}>
      {sender != null && (
        <div className="mb-1 px-3.5 text-xs text-muted-foreground">
          {sender}
        </div>
      )}
      <Message align={isUser ? "end" : "start"}>
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
                <div
                  className={cn("flex flex-col gap-2.5 py-1", text && "mb-1")}
                >
                  {blocks.map((attachment) => (
                    <AttachmentContent
                      key={attachment.id}
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
    </div>
  );
}
