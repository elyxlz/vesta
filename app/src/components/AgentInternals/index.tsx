import { useLayoutEffect, useRef } from "react";
import { useAgentWs } from "@/hooks/use-agent-ws";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { linkify } from "@/lib/linkify";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AgentInternals() {
  const { name } = useSelectedAgent();
  const { messages, connected } = useAgentWs(name, true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const { check, scroll } = useAutoScroll();

  const filteredMessages = messages.filter(
    (m) => m.type !== "status" && m.type !== "history",
  );

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [filteredMessages, scroll]);

  const handleScroll = () => {
    check(scrollRef.current);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 min-h-11 shrink-0 border-b border-border/50">
        <span className="text-sm font-medium">agent internals</span>
        <span className={cn(
          "text-xs",
          connected ? "text-emerald-500" : "text-muted-foreground",
        )}>
          {connected ? "connected" : "disconnected"}
        </span>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-xs leading-[1.6]"
      >
        <div className="min-h-full flex flex-col justify-end">
          <div>
            {filteredMessages.length === 0 && (
              <div className="flex flex-col items-center gap-2 py-1">
                <span className="text-xs text-muted-foreground">
                  {connected ? "waiting for activity..." : "connecting..."}
                </span>
              </div>
            )}

            {filteredMessages.map((msg, i) => (
              <InternalsLine key={i} event={msg} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function InternalsLine({ event }: { event: VestaEvent }) {
  if (event.type === "history" || event.type === "status") return null;

  const ts = event.ts
    ? new Date(event.ts).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
    : "";

  let colorClass = "text-foreground/70";
  let content = "";

  switch (event.type) {
    case "user":
      colorClass = "text-foreground font-medium";
      content = `> ${event.text}`;
      break;
    case "assistant":
      colorClass = "text-primary/90";
      content = event.text;
      break;
    case "tool_start":
      colorClass = "text-muted-foreground";
      content = `[${event.tool}] ${event.input}`;
      break;
    case "tool_end":
      colorClass = "text-muted-foreground";
      content = `[${event.tool}] done`;
      break;
    case "notification":
      colorClass = "text-amber-600 dark:text-amber-400";
      content = `[${event.source}] ${event.summary}`;
      break;
    case "error":
      colorClass = "text-destructive";
      content = `error: ${event.text}`;
      break;
    default:
      return null;
  }

  return (
    <div className={cn("flex gap-2 py-[1px]", colorClass)}>
      {ts && (
        <span className="text-muted-foreground/40 shrink-0 leading-[1.6] select-none">
          {ts}
        </span>
      )}
      <span
        className="break-words min-w-0"
        dangerouslySetInnerHTML={{ __html: linkify(content) }}
      />
    </div>
  );
}
