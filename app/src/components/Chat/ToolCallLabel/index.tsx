import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";

export function ToolCallLabel({
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
    <div className={cn("flex flex-col items-start max-w-[85%]", className)}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 rounded-full border border-muted-foreground/15 bg-muted/50 px-2.5 py-1 cursor-pointer hover:bg-muted/80 transition-colors"
      >
        <Wrench className="size-3 text-muted-foreground/60" />
        <span className="text-[11px] text-muted-foreground/70">{tool}</span>
        <motion.span
          animate={{ rotate: expanded ? 90 : 0 }}
          transition={{ duration: 0.15 }}
          className="flex items-center"
        >
          <ChevronRight className="size-3 text-muted-foreground/40" />
        </motion.span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.pre
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="mt-1 w-full overflow-hidden rounded-lg border border-muted-foreground/10 bg-muted/30 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground/70 whitespace-pre-wrap break-words font-mono"
          >
            {input}
          </motion.pre>
        )}
      </AnimatePresence>
    </div>
  );
}
