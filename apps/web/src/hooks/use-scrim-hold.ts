import { useEffect, useState } from "react";
import { useScrim } from "@/stores/use-scrim";

// One overlay's grip on the app scrim: held while open, released on close or
// unmount. Lives in the overlay root wrappers (popover, dropdown, dialog), so
// every usage participates without wiring.
function useScrimHold(open: boolean) {
  useEffect(() => {
    if (!open) return;
    useScrim.getState().acquire();
    return () => {
      useScrim.getState().release();
    };
  }, [open]);
}

// The root-wrapper form: tracks open across controlled and uncontrolled usage
// (Radix roots emit onOpenChange either way), holds the scrim while open, and
// returns the composed onOpenChange to pass through to the primitive root.
// `enabled: false` keeps the tracking but skips the hold (the drawer-mode
// dialog keeps vaul's own drag-tracking overlay instead).
export function useOverlayScrim(
  props: {
    open?: boolean;
    defaultOpen?: boolean;
    onOpenChange?: (open: boolean) => void;
  },
  { enabled = true }: { enabled?: boolean } = {},
): (open: boolean) => void {
  const [uncontrolled, setUncontrolled] = useState(props.defaultOpen ?? false);
  const isOpen = props.open ?? uncontrolled;
  useScrimHold(enabled && isOpen);
  return (next: boolean) => {
    setUncontrolled(next);
    props.onOpenChange?.(next);
  };
}
