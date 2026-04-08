import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export function ThinkingDots({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 py-1", className)}>
      <span className="text-xs text-muted-foreground">Thinking</span>
      <div className="flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="size-[5px] rounded-full bg-primary"
            animate={{ opacity: [0.25, 1, 0.25] }}
            transition={{
              duration: 1.5,
              repeat: Infinity,
              ease: "easeInOut",
              delay: i * 0.3,
            }}
          />
        ))}
      </div>
    </div>
  );
}
