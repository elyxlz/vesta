import * as React from "react";
import { DropdownMenu as DropdownMenuPrimitive } from "radix-ui";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { DropdownMenu as UiDropdownMenu } from "@/components/ui/dropdown-menu";

// The app's dropdown root: the stock primitive holding the app scrim (components/Scrim) while open.
// `scrim={false}` opens it over an undimmed page, for a small menu that is part of its trigger.
function DropdownMenu({
  scrim = true,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Root> & {
  scrim?: boolean;
}) {
  const handleOpenChange = useOverlayScrim(
    {
      open: props.open,
      defaultOpen: props.defaultOpen,
      onOpenChange: (next) => props.onOpenChange?.(next),
    },
    { enabled: scrim },
  );
  return <UiDropdownMenu {...props} onOpenChange={handleOpenChange} />;
}

export { DropdownMenu };
export {
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
