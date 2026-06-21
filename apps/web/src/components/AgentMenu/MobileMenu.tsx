import { DrawerClose } from "@/components/ui/drawer";
import { Drawer, DrawerContent, DrawerTrigger } from "@/components/ui/drawer";
import { AgentActions, menuActionsInput } from "./AgentActions";
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
            {...menuActionsInput(state)}
            wrapper={DrawerCloseWrapper}
          />
        </div>
      </DrawerContent>
    </Drawer>
  );
}
