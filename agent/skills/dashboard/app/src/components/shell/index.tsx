import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  isFullscreen as getFullscreen,
  onLayoutChange,
} from "@/lib/parent-bridge"

export function Shell({ className, ...props }: React.ComponentProps<"div">) {
  const [fullscreen, setFullscreen] = useState(getFullscreen)

  useEffect(() => onLayoutChange(setFullscreen), [])

  return (
    <div
      data-fullscreen={fullscreen}
      className={cn(
        "bg-card text-card-foreground overflow-hidden contain-paint",
        fullscreen
          ? "h-full w-full"
          : "m-2 h-[calc(100%-1rem)] w-[calc(100%-1rem)] rounded-4xl shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10",
        className,
      )}
      {...props}
    />
  )
}
