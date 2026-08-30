import { AnimatePresence, motion } from "motion/react";
import { Upload } from "lucide-react";
import { fade } from "@/lib/motion";

export function DropOverlay({
  active,
  agentName,
}: {
  active: boolean;
  agentName: string;
}) {
  return (
    <AnimatePresence>
      {active && (
        <motion.div
          {...fade}
          className="pointer-events-none absolute inset-0 z-30 bg-background/70 p-4"
        >
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-primary/50 bg-popover/80 text-muted-foreground">
            <Upload className="size-7" />
            <span className="text-sm">drop to send to {agentName}</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
