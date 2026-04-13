import { useState, useEffect, useRef, createContext, useContext } from "react"
import { cn } from "@/lib/utils"
import {
  isFullscreen as getFullscreen,
  onLayoutChange,
} from "@/lib/parent-bridge"

const ShellRefContext = createContext<React.RefObject<HTMLDivElement | null>>({ current: null })

export function useShellRef() {
  return useContext(ShellRefContext)
}

export function Shell({ className, ...props }: React.ComponentProps<"div">) {
  const [fullscreen, setFullscreen] = useState(getFullscreen)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => onLayoutChange(setFullscreen), [])

  return (
    <ShellRefContext.Provider value={ref}>
      <div
        ref={ref}
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
    </ShellRefContext.Provider>
  )
}
