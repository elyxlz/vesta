import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  isFullscreen as getFullscreen,
  onLayoutChange,
} from "@/lib/parent-bridge"

//  Do not touch this file. 

export function Shell({ className, ...props }: React.ComponentProps<"div">) {
  const [fullscreen, setFullscreen] = useState(getFullscreen)

  useEffect(() => onLayoutChange(setFullscreen), [])

  return (
    <div
      className={cn(
        "h-full w-full text-card-foreground overflow-hidden contain-paint",
        fullscreen ? "" : "bg-card rounded-4xl shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10",
        className,
      )}
      {...props}
    />
  )
}
