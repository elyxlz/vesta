import { memo } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
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
  return (
    <div className={cn("flex max-w-[85%]", className)}>
      {/* The Collapsible root IS the pill: it morphs (corner radius + padding) between the
          closed label and the open label-over-input — instantly, no animation — rather than
          dropping a separate box below. */}
      <Collapsible className="group/tool min-w-0 overflow-hidden rounded-full border border-muted-foreground/15 bg-muted/50 data-[state=open]:rounded-2xl">
        <CollapsibleTrigger asChild>
          <Marker
            asChild
            className="w-fit cursor-pointer gap-1.5 px-2.5 py-1 hover:bg-muted/80 data-[state=open]:px-3 data-[state=open]:pt-2 data-[state=open]:pb-1.5"
          >
            <button type="button">
              <MarkerIcon className="size-3 text-muted-foreground">
                <Wrench className="size-3" />
              </MarkerIcon>
              <MarkerContent className="whitespace-nowrap text-[11px] text-muted-foreground">
                {TOOL_LABELS[tool] ?? tool}
              </MarkerContent>
              <ChevronRight className="size-3 text-muted-foreground/70 transition-transform group-data-[state=open]/tool:rotate-90" />
            </button>
          </Marker>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="w-full whitespace-pre-wrap break-words px-3 pb-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
            {input}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
});
