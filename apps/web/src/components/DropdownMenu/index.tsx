import * as React from "react";
import { DropdownMenu as DropdownMenuPrimitive } from "radix-ui";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { DropdownMenu as UiDropdownMenu } from "@/components/ui/dropdown-menu";

// The app's dropdown root: the stock primitive holding the app scrim (components/Scrim) while open.
function DropdownMenu(
  props: React.ComponentProps<typeof DropdownMenuPrimitive.Root>,
) {
  const handleOpenChange = useOverlayScrim({
    open: props.open,
    defaultOpen: props.defaultOpen,
    onOpenChange: (next) => props.onOpenChange?.(next),
  });
  return <UiDropdownMenu {...props} onOpenChange={handleOpenChange} />;
}

export { DropdownMenu };
export {
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
