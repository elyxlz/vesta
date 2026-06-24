import { memo, useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";

const TOOL_LABELS: Record<string, string> = {
  Bash: "ran a command",
  Read: "read a file",
  Write: "wrote a file",
  Edit: "edited a file",
  Glob: "searched for files",
  Grep: "searched the code",
  WebFetch: "fetched a page",
  WebSearch: "searched the web",
  TodoWrite: "updated the todo list",
  Task: "ran a subtask",
};

export const ToolCallLabel = memo(function ToolCallLabel({
  tool,
  input,
  className,
}: {
  tool: string;
  input: string;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={cn("flex max-w-[85%]", className)}>
      {/* The pill IS the container: it switches (size + corner radius) to wrap the input on
          expand — instantly, no animation — rather than dropping a separate box below. */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "flex min-w-0 cursor-pointer flex-col items-start overflow-hidden border border-muted-foreground/15 bg-muted/50 text-left hover:bg-muted/80",
          expanded
            ? "gap-1.5 rounded-2xl px-3 py-2"
            : "rounded-full px-2.5 py-1",
        )}
      >
        <div className="flex items-center gap-1.5">
          <Wrench className="size-3 shrink-0 text-muted-foreground/60" />
          <span className="whitespace-nowrap text-[11px] text-muted-foreground/70">
            {TOOL_LABELS[tool] ?? tool}
          </span>
          <ChevronRight
            className={cn(
              "size-3 text-muted-foreground/40",
              expanded && "rotate-90",
            )}
          />
        </div>
        {expanded && (
          <pre className="w-full whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-muted-foreground/70">
            {input}
          </pre>
        )}
      </button>
    </div>
  );
});
