import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  MoreVertical,
  Play,
  ScrollText,
  Settings,
  Square,
  KeyRound,
  Wrench,
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
import { useChatContext } from "@/providers/ChatProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

function useNavigateToLogs() {
  const navigate = useNavigate();
  const { name } = useSelectedAgent();
  return () => navigate(`/agent/${encodeURIComponent(name)}/logs`);
}

export function AgentMenu() {
  const navigate = useNavigate();
  const {
    name,
    agent,
    isBusy,
    start,
    stop,
    restart,
    rebuild,
    backup,
  } = useSelectedAgent();
  const {
    handleOpenAuth,
    setDeleteDialogOpen,
  } = useModals();
  const goToLogs = useNavigateToLogs();
  const { showToolCalls, setShowToolCalls } = useChatContext();

  const [open, setOpen] = useState(false);
  const isMobile = useIsMobile();

  const isRunning = agent?.status === "running";
  const showAuthenticate = isRunning && !agent?.authenticated;
  const showAliveActions = agent?.alive;

  const trigger = (
    <Button size="icon-sm" variant="outline" className="md:size-9" aria-label="agent actions">
      <MoreVertical />
    </Button>
  );

  const reauthenticateButton = showAuthenticate && !isMobile && (
    <Button size="sm" onClick={() => void handleOpenAuth()}>
      <KeyRound data-icon="inline-start" />
      reauthenticate
    </Button>
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={setOpen}>
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
            {showAuthenticate && (
              <DrawerClose asChild>
                <Button
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => void handleOpenAuth()}
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
                onClick={() => void (isRunning ? stop() : start())}
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
            {!showAliveActions && (
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start"
                onClick={() => setShowToolCalls((v) => !v)}
              >
                <Wrench data-icon="inline-start" />
                {showToolCalls ? "hide tool calls" : "show tool calls"}
              </Button>
            )}
            {showAliveActions && (
              <>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    onClick={goToLogs}
                  >
                    <ScrollText data-icon="inline-start" />
                    logs
                  </Button>
                </DrawerClose>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => setShowToolCalls((v) => !v)}
                >
                  <Wrench data-icon="inline-start" />
                  {showToolCalls ? "hide tool calls" : "show tool calls"}
                </Button>
                <DrawerClose asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full justify-start"
                    onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}
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
                    onClick={() => void restart()}
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
                    onClick={() => void rebuild()}
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
                onClick={() => void backup()}
              >
                backup
              </Button>
            </DrawerClose>
            <DrawerClose asChild>
              <Button
                size="sm"
                variant="destructive"
                className="w-full justify-start"
                disabled={isBusy}
                onClick={() => setDeleteDialogOpen(true)}
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
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {reauthenticateButton ? (
        <div className="flex items-center gap-1.5">
          {reauthenticateButton}
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        </div>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="end" side="bottom" className="min-w-[180px]">
        {showAuthenticate && (
          <DropdownMenuItem onClick={() => void handleOpenAuth()}>
            <KeyRound data-icon="inline-start" />
            authenticate
          </DropdownMenuItem>
        )}
        <DropdownMenuItem disabled={isBusy} onClick={() => void (isRunning ? stop() : start())}>
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
        {!showAliveActions && (
          <DropdownMenuItem onClick={() => setShowToolCalls((v) => !v)}>
            <Wrench />
            {showToolCalls ? "hide tool calls" : "show tool calls"}
          </DropdownMenuItem>
        )}
        {showAliveActions && (
          <>
            <DropdownMenuItem onClick={goToLogs}>
              <ScrollText data-icon="inline-start" />
              logs
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setShowToolCalls((v) => !v)}>
              <Wrench />
              {showToolCalls ? "hide tool calls" : "show tool calls"}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}>
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
                <DropdownMenuItem disabled={isBusy} onClick={() => void restart()}>
                  restart
                </DropdownMenuItem>
              </TooltipTrigger>
              <TooltipContent side="left">restart agent</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuItem disabled={isBusy} onClick={() => void rebuild()}>
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
            <DropdownMenuItem disabled={isBusy} onClick={() => void backup()}>
              backup
            </DropdownMenuItem>
          </TooltipTrigger>
          <TooltipContent side="left">create a snapshot</TooltipContent>
        </Tooltip>
        <DropdownMenuSeparator />
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuItem variant="destructive" disabled={isBusy} onClick={() => setDeleteDialogOpen(true)}>
              delete
            </DropdownMenuItem>
          </TooltipTrigger>
          <TooltipContent side="left">permanently delete</TooltipContent>
        </Tooltip>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
