import { DrawerClose } from "@/components/ui/drawer";
import { Drawer, DrawerContent, DrawerTrigger } from "@/components/ui/drawer";
import { AgentActions } from "./AgentActions";
import type { MenuProps } from "./types";

function DrawerCloseWrapper({ children }: { children: React.ReactNode }) {
  return <DrawerClose asChild>{children}</DrawerClose>;
}

export function MobileMenu({ state, open, onOpenChange, trigger }: MenuProps) {
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerTrigger asChild>{trigger}</DrawerTrigger>
      <DrawerContent>
        <div className="px-4 pb-8 max-h-[min(70vh,480px)] overflow-y-auto">
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
            onOpenSettings={state.onOpenSettings}
            onDebugInfo={state.onDebugInfo}
            wrapper={DrawerCloseWrapper}
          />
        </div>
      </DrawerContent>
    </Drawer>
  );
}
