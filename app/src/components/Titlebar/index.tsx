import { useCallback } from "react";
import { LogOut, Minus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";
import { getConnection, clearConnection } from "@/lib/connection";
import { useAppStore } from "@/stores/use-app-store";

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

  if (!isTauri && !connected) return null;

  return (
    <div
      className="flex items-center justify-between h-9 px-3 select-none shrink-0"
      style={{ paddingLeft: isTauri && platform === "macos" ? 78 : undefined }}
      onMouseDown={handleDrag}
    >
      <div className="flex-1" />

      <div className="window-controls flex items-center gap-1">
        {connected && (
          <>
            <div className="w-[6px] h-[6px] rounded-full bg-primary shrink-0" />
            <span className="text-xs text-muted-foreground truncate">{hostname}</span>
          </>
        )}
        {connected && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={handleDisconnect}
              >
                <LogOut size={13} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>disconnect</TooltipContent>
          </Tooltip>
        )}

        {isTauri && platform !== "macos" && (
          <>
            {platform === "linux" ? (
              <>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={handleMinimize}
                >
                  <Minus size={13} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={handleClose}
                  className="hover:bg-destructive/10 hover:text-destructive"
                >
                  <X size={13} />
                </Button>
              </>
            ) : (
              <>
                <button
                  onClick={handleMinimize}
                  className="w-[46px] h-[32px] flex items-center justify-center hover:bg-accent transition-colors"
                >
                  <Minus size={13} />
                </button>
                <button
                  onClick={handleClose}
                  className="w-[46px] h-[32px] flex items-center justify-center hover:bg-destructive hover:text-destructive-foreground transition-colors"
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
