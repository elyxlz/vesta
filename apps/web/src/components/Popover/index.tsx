import * as React from "react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { useOverlayScrim } from "@/hooks/use-scrim-hold";
import { Popover as UiPopover } from "@/components/ui/popover";

// The app's popover root: the stock primitive holding the app scrim (components/Scrim) while open.
function Popover({
  open,
  defaultOpen,
  onOpenChange,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  const handleOpenChange = useOverlayScrim({ open, defaultOpen, onOpenChange });
  return (
    <UiPopover
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={handleOpenChange}
      {...props}
    />
  );
}

export { Popover };
export { PopoverContent, PopoverTrigger } from "@/components/ui/popover";
