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
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerHeader,
  DrawerTrigger,
} from "@/components/ui/drawer";
import type { MenuProps } from "./types";

export function MobileMenu({ state, open, onOpenChange, trigger }: MenuProps) {
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerTrigger asChild>{trigger}</DrawerTrigger>
      <DrawerContent>
        <DrawerHeader>
        </DrawerHeader>
        <div className="flex flex-col gap-1 px-4 pb-8 max-h-[min(70vh,480px)] overflow-y-auto">
          <DrawerClose asChild>
            <Button
              size="sm"
              variant="outline"
              className="w-full justify-start"
              disabled={state.isBusy}
              onClick={state.onToggle}
            >
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
            </Button>
          </DrawerClose>
          {!state.showAliveActions && (
            <Button
              size="sm"
              variant="outline"
              className="w-full justify-start"
              onClick={state.onToolCalls}
            >
              <Wrench data-icon="inline-start" />
              {state.showToolCalls ? "hide tool calls" : "show tool calls"}
            </Button>
          )}
          {state.showAliveActions && (
            <>
              <DrawerClose asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full justify-start"
                  onClick={state.onLogs}
                >
                  <ScrollText data-icon="inline-start" />
                  logs
                </Button>
              </DrawerClose>
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start"
                onClick={state.onToolCalls}
              >
                <Wrench data-icon="inline-start" />
                {state.showToolCalls ? "hide tool calls" : "show tool calls"}
              </Button>
            </>
          )}
          {state.isRunning && (
            <>
              <DrawerClose asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full justify-start"
                  disabled={state.isBusy}
                  onClick={state.onRestart}
                >
                <RefreshCw data-icon="inline-start" />
                  restart
                </Button>
              </DrawerClose>
              <DrawerClose asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full justify-start"
                  disabled={state.isBusy}
                  onClick={state.onRebuild}
                >
                <Hammer data-icon="inline-start" />
                  rebuild
                </Button>
              </DrawerClose>
            </>
          )}
          <DrawerClose asChild>
            <Button
              size="sm"
              variant="outline"
              className="w-full justify-start"
              disabled={state.isBusy}
              onClick={state.onBackup}
            >
              <Archive data-icon="inline-start" />
              backup
            </Button>
          </DrawerClose>
          <DrawerClose asChild>
            <Button
              size="sm"
              variant="outline"
              className="w-full justify-start"
              onClick={state.onOpenSettings}
            >
              <Settings data-icon="inline-start" />
              settings
            </Button>
          </DrawerClose>
        </div>
      </DrawerContent>
    </Drawer>
  );
}
