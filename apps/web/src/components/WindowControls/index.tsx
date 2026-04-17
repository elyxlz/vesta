import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, X } from "lucide-react";
import { useTauri } from "@/providers/TauriProvider";

export function WindowControls() {
  const { isLinux, isTauri } = useTauri();

  if (!isTauri || !isLinux) return null;

  const win = getCurrentWindow();

  return (
    <div className="flex items-center gap-0.5 ml-2">
      <button
        onClick={() => win.minimize()}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        <Minus className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={() => win.toggleMaximize()}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        <Square className="h-3 w-3" />
      </button>
      <button
        onClick={() => win.close()}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive hover:text-white transition-colors"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
