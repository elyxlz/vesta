import { AnimatePresence, motion } from "motion/react";
import { usePrefersReducedMotion } from "@/hooks/use-reduced-motion";

interface ProgressBarProps {
  message?: string;
}

export function ProgressBar({ message }: ProgressBarProps) {
  const prefersReducedMotion = usePrefersReducedMotion();

  return (
    <div className="flex flex-col items-center gap-2 w-full">
      <div className="w-full max-w-[200px] h-[3px] bg-foreground/5 rounded-full overflow-hidden">
        {prefersReducedMotion ? (
          <motion.div
            className="h-full w-full bg-foreground/30 rounded-full"
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{
              duration: 1.5,
              ease: "easeInOut",
              repeat: Infinity,
              repeatType: "loop",
            }}
          />
        ) : (
          <motion.div
            className="h-full w-1/3 bg-foreground/30 rounded-full"
            initial={{ x: "-100%" }}
            animate={{ x: "400%" }}
            transition={{
              duration: 1.5,
              ease: "easeInOut",
              repeat: Infinity,
              repeatType: "loop",
            }}
          />
        )}
      </div>
      <p
        role="status"
        aria-live="polite"
        className="text-xs text-muted-foreground whitespace-pre-line"
      >
        <AnimatePresence mode="wait">
          {message && (
            <motion.span
              key={message}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {message}
            </motion.span>
          )}
        </AnimatePresence>
      </p>
    </div>
  );
}
