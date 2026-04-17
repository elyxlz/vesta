import { motion } from "motion/react";
import { cn } from "@/lib/utils";

interface AnimatedEllipsisProps {
  size?: number;
  color?: string;
  className?: string;
}

export function AnimatedEllipsis({
  size = 5,
  color = "bg-current",
  className,
}: AnimatedEllipsisProps) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 align-middle", className)}
    >
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className={cn("rounded-full", color)}
          style={{ width: size, height: size }}
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: "easeInOut",
            delay: i * 0.3,
          }}
        />
      ))}
    </span>
  );
}
