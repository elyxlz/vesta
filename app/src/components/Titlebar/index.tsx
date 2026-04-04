import { Minus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";

export function Titlebar() {
  const platform = detectPlatform();

  if (!isTauri || platform === "ios" || platform === "android") return null;

  const handleDrag = async (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest("button")) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().startDragging();
  };

  const handleMinimize = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().minimize();
  };

  const handleClose = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().close();
  };

  return (
    <div
      data-tauri-drag-region
      className="fixed left-0 right-0 z-[100] flex items-center justify-end h-7 select-none"
      style={{
        top: "env(safe-area-inset-top)",
        paddingLeft: platform === "macos" ? 78 : undefined,
      }}
      onMouseDown={handleDrag}
    >
      {platform !== "macos" && (
        <>
          {platform === "linux" ? (
            <>
              <Button variant="ghost" size="icon" onClick={handleMinimize}>
                <Minus />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={handleClose}
                className="hover:bg-[#c42b1c]/10 hover:text-[#c42b1c]"
              >
                <X />
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={handleMinimize}
                className="w-[46px] h-9 rounded-none"
              >
                <Minus />
              </Button>
              <Button
                variant="ghost"
                onClick={handleClose}
                className="w-[46px] h-9 rounded-none hover:bg-[#c42b1c] hover:text-white"
              >
                <X />
              </Button>
            </>
          )}
        </>
      )}
    </div>
  );
}
