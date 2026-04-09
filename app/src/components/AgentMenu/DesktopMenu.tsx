import {
  Archive,
  Play,
  RefreshCw,
  ScrollText,
  Settings,
  Square,
  Wrench,
  Hammer,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { MenuProps } from "./types";

export function DesktopMenu({
  state,
  open,
  onOpenChange,
  trigger,
}: MenuProps) {
  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="bottom" className="min-w-[180px]">
        <DropdownMenuItem disabled={state.isBusy} onClick={state.onToggle}>
          {state.isRunning ? (
            <>
              <Square data-icon="inline-start" />
              stop
            </>
          ) : (
            <>
              <Play data-icon="inline-start" />
              start
            </>
          )}
        </DropdownMenuItem>
        {!state.showAliveActions && (
          <DropdownMenuItem onClick={state.onToolCalls}>
            <Wrench />
            {state.showToolCalls ? "hide tool calls" : "show tool calls"}
          </DropdownMenuItem>
        )}
        {state.showAliveActions && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={state.onLogs}>
              <ScrollText data-icon="inline-start" />
              logs
            </DropdownMenuItem>
            <DropdownMenuItem onClick={state.onToolCalls}>
              <Wrench />
              {state.showToolCalls ? "hide tool calls" : "show tool calls"}
            </DropdownMenuItem>
          </>
        )}
        {state.isRunning && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={state.isBusy}
              onClick={state.onRestart}
            >
              <RefreshCw data-icon="inline-start" />
              restart
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={state.isBusy}
              onClick={state.onRebuild}
            >
              <Hammer data-icon="inline-start" />
              rebuild
            </DropdownMenuItem>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={state.isBusy} onClick={state.onBackup}>
          <Archive data-icon="inline-start" />
          backup
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={state.onOpenSettings}>
          <Settings data-icon="inline-start" />
          settings
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
