import { KeyRound } from "lucide-react";
import { DrawerClose } from "@/components/ui/drawer";
import { Drawer, DrawerContent, DrawerTrigger } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { AgentActions } from "./AgentActions";
import type { MenuProps } from "./types";

function DrawerCloseWrapper({ children }: { children: React.ReactNode }) {
  return <DrawerClose asChild>{children}</DrawerClose>;
}

export function MobileMenu({ state, open, onOpenChange, trigger }: MenuProps) {
  // An agent that needs auth is an urgent action: surface "sign in" as a primary
  // button at the top of the drawer, and drop the routine auth row from the list
  // below so it isn't shown twice (the list keeps "switch provider" once authed).
  const needsAuth = !!state.onAuthenticate && !state.isAuthenticated;

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerTrigger asChild>{trigger}</DrawerTrigger>
      <DrawerContent>
        <div className="px-4 pb-8 max-h-[min(70vh,480px)] overflow-y-auto">
          {needsAuth && (
            <DrawerClose asChild>
              <Button
                variant="default"
                size="lg"
                className="mb-4 w-full"
                onClick={() => state.onAuthenticate?.()}
              >
                <KeyRound data-icon="inline-start" />
                sign in
              </Button>
            </DrawerClose>
          )}
          <AgentActions
            isRunning={state.isRunning}
            showAliveActions={state.showAliveActions}
            isBusy={state.isBusy}
            showToolCalls={state.showToolCalls}
            onLogs={state.onLogs}
            onToolCalls={state.onToolCalls}
            onToggle={state.onToggle}
            onRestart={state.onRestart}
            onRebuild={state.onRebuild}
            onBackup={state.onBackup}
            onAppSettings={state.onAppSettings}
            onAgentSettings={state.onAgentSettings}
            onAuthenticate={
              state.isAuthenticated ? state.onAuthenticate : undefined
            }
            isAuthenticated={state.isAuthenticated}
            onDebugInfo={state.onDebugInfo}
            wrapper={DrawerCloseWrapper}
          />
        </div>
      </DrawerContent>
    </Drawer>
  );
}
