import { AnimatePresence, motion } from "motion/react";

interface ProgressBarProps {
  message?: string;
}

export function ProgressBar({ message }: ProgressBarProps) {
  return (
    <div className="flex flex-col items-center gap-2 w-full">
      <div className="w-full max-w-[200px] h-[3px] bg-foreground/5 rounded-full overflow-hidden">
        <div
          className="h-full w-1/3 bg-foreground/30 rounded-full"
          style={{ animation: "progress-indeterminate 1.5s ease-in-out infinite" }}
        />
      </div>
      <AnimatePresence mode="wait">
        {message && (
          <motion.p
            key={message}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="text-xs text-muted-foreground"
          >
            {message}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
