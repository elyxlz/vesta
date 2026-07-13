import { useEffect, useState } from "react";
import { Copy, Minus, Square, X } from "lucide-react";
import { native } from "@/lib/native";

// Custom min/max/close for platforms where the app draws its own title-bar
// controls (Windows); null on macOS (native traffic lights) and in the browser.
export function WindowControls() {
  const controls = native.windowControls;
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!controls) return;
    let active = true;
    void controls.isMaximized().then((m) => {
      if (active) setMaximized(m);
    });
    const unsubscribe = controls.onMaximizedChange(setMaximized);
    return () => {
      active = false;
      unsubscribe();
    };
  }, [controls]);

  if (!controls) return null;

  return (
    <div className="ml-1.5 flex items-center gap-1">
      <button
        aria-label="minimize"
        onClick={() => controls.minimize()}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <Minus className="size-4" />
      </button>
      <button
        aria-label={maximized ? "restore" : "maximize"}
        onClick={() => controls.toggleMaximize()}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        {maximized ? <Copy className="size-3.5" /> : <Square className="size-3.5" />}
      </button>
      <button
        aria-label="close"
        onClick={() => controls.close()}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive hover:text-white"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}
