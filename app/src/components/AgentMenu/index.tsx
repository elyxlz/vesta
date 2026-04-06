import {
  Activity,
  MoreVertical,
  Play,
  ScrollText,
  Settings,
  Square,
  KeyRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsMobile } from "@/hooks/use-mobile";
import type { AgentInfo } from "@/lib/types";

type AgentMenuProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  info: Pick<AgentInfo, "status" | "authenticated" | "alive"> | null;
  isBusy: boolean;
  authenticateBesideTrigger?: boolean;
  onAuthOpen: () => void | Promise<void>;
  onStart: () => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onRestart: () => void | Promise<void>;
  onRebuild: () => void | Promise<void>;
  onBackup: () => void | Promise<void>;
  onShowBackups: () => void;
  onShowConsole: () => void;
  onShowInternals: () => void;
  onShowAgentSettings: () => void;
  onOpenDeleteDialog: () => void;
};

export function AgentMenu({
  open,
  onOpenChange,
  name,
  info,
  isBusy,
  authenticateBesideTrigger = false,
  onAuthOpen,
  onStart,
  onStop,
  onRestart,
  onRebuild,
  onBackup,
  onShowBackups,
  onShowConsole,
  onShowInternals,
  onShowAgentSettings,
  onOpenDeleteDialog,
}: AgentMenuProps) {
  const isMobile = useIsMobile();

  const isRunning = info?.status === "running";
  const showAuthenticate = isRunning && !info?.authenticated;
  const showAuthenticateInMenu = showAuthenticate && !authenticateBesideTrigger;
  const showAliveActions = info?.alive;

  const trigger = (
    <Button size="icon-sm" variant="outline" className="md:size-9" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  const reauthenticateButton = showAuthenticate && authenticateBesideTrigger && (
    <Button size="sm" onClick={() => void onAuthOpen()}>
      <KeyRound data-icon="inline-start" />
      reauthenticate
    </Button>
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange}>
        {reauthenticateButton ? (
          <div className="flex items-center gap-1.5">
            {reauthenticateButton}
            <DrawerTrigger asChild>{trigger}</DrawerTrigger>
          </div>
        ) : (
          <DrawerTrigger asChild>{trigger}</DrawerTrigger>
        )}
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle className="text-left">{name}</DrawerTitle>
          </DrawerHeader>
          <div className="flex flex-col gap-1 px-4 pb-8 max-h-[min(70vh,480px)] overflow-y-auto">
            {showAuthenticateInMenu && (
              <DrawerClose asChild>
                <Button
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => {
                    void onAuthOpen();
                  }}
                >
                  <KeyRound data-icon="inline-start" />
                  authenticate
                </Button>
              </DrawerClose>
            )}
            <DrawerClose asChild>
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start"
                disabled={isBusy}
                onClick={() => {
                  void (isRunning ? onStop() : onStart());
                }}
              >
                {isRunning ? (
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
            {showAliveActions && (
              <>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    onClick={onShowConsole}
                  >
                    <ScrollText data-icon="inline-start" />
                    logs
                  </Button>
                </DrawerClose>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    onClick={onShowInternals}
                  >
                    <Activity data-icon="inline-start" />
                    internals
                  </Button>
                </DrawerClose>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    onClick={onShowAgentSettings}
                  >
                    <Settings data-icon="inline-start" />
                    settings
                  </Button>
                </DrawerClose>
              </>
            )}
            {isRunning && (
              <>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    disabled={isBusy}
                    onClick={() => {
                      void onRestart();
                    }}
                  >
                    restart
                  </Button>
                </DrawerClose>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    disabled={isBusy}
                    onClick={() => {
                      void onRebuild();
                    }}
                  >
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
                disabled={isBusy}
                onClick={() => {
                  void onBackup();
                }}
              >
                backup
              </Button>
            </DrawerClose>
            <DrawerClose asChild>
              <Button size="sm" variant="outline" className="w-full justify-start" onClick={onShowBackups}>
                backups
              </Button>
            </DrawerClose>
            <DrawerClose asChild>
              <Button
                size="sm"
                variant="destructive"
                className="w-full justify-start"
                disabled={isBusy}
                onClick={onOpenDeleteDialog}
              >
                delete
              </Button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      {reauthenticateButton ? (
        <div className="flex items-center gap-1.5">
          {reauthenticateButton}
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        </div>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="center" side="bottom" className="min-w-[180px]">
        {showAuthenticateInMenu && (
          <DropdownMenuItem onClick={() => void onAuthOpen()}>
            <KeyRound data-icon="inline-start" />
            authenticate
          </DropdownMenuItem>
        )}
        <DropdownMenuItem disabled={isBusy} onClick={() => void (isRunning ? onStop() : onStart())}>
          {isRunning ? (
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
        {showAliveActions && (
          <>
            <DropdownMenuItem onClick={onShowConsole}>
              <ScrollText data-icon="inline-start" />
              logs
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onShowInternals}>
              <Activity data-icon="inline-start" />
              internals
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onShowAgentSettings}>
              <Settings data-icon="inline-start" />
              settings
            </DropdownMenuItem>
          </>
        )}
        {isRunning && (
          <>
            <DropdownMenuSeparator />
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuItem disabled={isBusy} onClick={() => void onRestart()}>
                  restart
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent side="left">restart agent</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuItem disabled={isBusy} onClick={() => void onRebuild()}>
                  rebuild
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent side="left">rebuild container from latest image</TooltipContent>
            </Tooltip>
          </>
        )}
        <DropdownMenuSeparator />
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuItem disabled={isBusy} onClick={() => void onBackup()}>
              backup
            </DropdownMenuItem>
          </TooltipTrigger>
          <TooltipContent side="left">create a snapshot</TooltipContent>
        </Tooltip>
        <DropdownMenuItem onClick={onShowBackups}>
          backups
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuItem variant="destructive" disabled={isBusy} onClick={onOpenDeleteDialog}>
              delete
            </DropdownMenuItem>
          </TooltipTrigger>
          <TooltipContent side="left">permanently delete</TooltipContent>
        </Tooltip>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
