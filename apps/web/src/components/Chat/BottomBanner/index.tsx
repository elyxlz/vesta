import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";

interface BottomBannerProps {
  error: string | null;
}

// A transient error pill above the composer. (Reconnect state is handled elsewhere — no pill for it.)
export function BottomBanner({ error }: BottomBannerProps) {
  return (
    <AnimatePresence>
      {error && (
        <motion.div
          key="error"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className={cn(
            "absolute top-0 left-1/2 z-10 -my-1.5 max-w-[100%] -translate-x-1/2 -translate-y-1/2 rounded-full border px-3 py-2 text-center text-xs shadow-sm",
            "bg-card text-destructive border-destructive/30 shadow-sm",
          )}
        >
          {error}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
