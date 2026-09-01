import { cn } from "@/lib/utils";

// A determinate progress ring: a border track under a primary arc that fills clockwise as
// `progress` runs 0 to 1. Shared by the composer's upload chips and attachment downloads.
export function ProgressRing({
  progress,
  className,
}: {
  progress: number;
  className?: string;
}) {
  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 20 20" className={cn("size-5 -rotate-90", className)}>
      <circle
        cx="10"
        cy="10"
        r={radius}
        fill="none"
        strokeWidth="2.5"
        className="stroke-border"
      />
      <circle
        cx="10"
        cy="10"
        r={radius}
        fill="none"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - progress)}
        className="stroke-primary transition-[stroke-dashoffset] duration-300"
      />
    </svg>
  );
}
