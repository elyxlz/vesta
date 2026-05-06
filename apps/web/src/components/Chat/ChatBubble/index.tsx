import { useIsMobile } from "@/hooks/use-mobile";
import { Markdown } from "@/lib/markdown";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ToolCallLabel } from "../ToolCallLabel";

export function ChatBubble({
  event,
  className,
  fullscreen,
}: {
  event: VestaEvent;
  className?: string;
  fullscreen?: boolean;
}) {
  const isMobile = useIsMobile();
  if (event.type === "history" || event.type === "status") return null;

  const ts = event.ts
    ? new Date(event.ts).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "";

  if (event.type === "error") {
    return (
      <div className={cn("flex justify-center px-4 py-1", className)}>
        <span className="text-xs text-destructive">{event.text}</span>
      </div>
    );
  }

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

  return (
    <div
      className={cn(
        "flex",
        isUser ? "justify-end" : "justify-start",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-end max-w-[85%] rounded-squircle-sm [corner-shape:squircle] px-3 py-1.5 text-sm leading-relaxed",
          fullscreen &&
            isMobile &&
            "shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : cn(
                "text-secondary-foreground rounded-bl-sm",
                fullscreen && isMobile ? "bg-card" : "bg-secondary",
              ),
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
      </div>
    </div>
  );
}
