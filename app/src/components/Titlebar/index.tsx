import { useCallback } from "react";
import { LogOut, Minus, X } from "lucide-react";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";
import { getConnection, clearConnection } from "@/lib/connection";
import { useAppStore } from "@/stores/use-app-store";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function Titlebar() {
  const connected = useAppStore((s) => s.connected);
  const disconnect = useAppStore((s) => s.disconnect);
  const platform = detectPlatform();

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  const handleDisconnect = useCallback(() => {
    clearConnection();
    disconnect();
  }, [disconnect]);

  const handleDrag = useCallback(async (e: React.MouseEvent) => {
    if (!isTauri) return;
    const target = e.target as HTMLElement;
    if (target.closest(".window-controls") || target.closest("button")) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().startDragging();
  }, []);

  const handleMinimize = useCallback(async () => {
    if (!isTauri) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().minimize();
  }, []);

  const handleClose = useCallback(async () => {
    if (!isTauri) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().close();
  }, []);

  return (
    <div
      className="flex items-center justify-between h-9 px-3 select-none shrink-0"
      style={{ paddingLeft: platform === "macos" ? 78 : undefined }}
      onMouseDown={handleDrag}
    >
      <div className="flex items-center gap-2 min-w-0">
        {connected && (
          <>
            <div className="w-[6px] h-[6px] rounded-full bg-green-500 shrink-0" />
            <span className="text-[11px] text-muted truncate">{hostname}</span>
          </>
        )}
      </div>

      <div className="window-controls flex items-center gap-1">
        {connected && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleDisconnect}
                className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-accent transition-colors"
              >
                <LogOut size={13} />
              </button>
            </TooltipTrigger>
            <TooltipContent>disconnect</TooltipContent>
          </Tooltip>
        )}

        {isTauri && platform !== "macos" && (
          <>
            {platform === "linux" ? (
              <>
                <button
                  onClick={handleMinimize}
                  className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-accent transition-colors"
                >
                  <Minus size={13} />
                </button>
                <button
                  onClick={handleClose}
                  className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-[#c42b1c]/10 hover:text-[#c42b1c] transition-colors"
                >
                  <X size={13} />
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={handleMinimize}
                  className="w-[46px] h-[32px] flex items-center justify-center text-muted hover:bg-accent transition-colors"
                >
                  <Minus size={13} />
                </button>
                <button
                  onClick={handleClose}
                  className="w-[46px] h-[32px] flex items-center justify-center text-muted hover:bg-[#c42b1c] hover:text-white transition-colors"
                >
                  <X size={13} />
                </button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
