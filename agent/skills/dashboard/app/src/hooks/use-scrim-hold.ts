// The synced ui/ primitives (dialog, dropdown-menu, popover) hold the web
// app's scrim through this hook. The dashboard shell renders in an iframe and
// has no scrim, so the hold is a no-op here; only the composed onOpenChange
// pass-through remains. Signature-identical to apps/web/src/hooks/use-scrim-hold.ts.
export function useScrimHold(_open: boolean): void {
  // No scrim in the dashboard shell.
}

export function useOverlayScrim(
  props: {
    open?: boolean;
    defaultOpen?: boolean;
    onOpenChange?: (open: boolean) => void;
  },
  _options: { enabled?: boolean } = {},
): (open: boolean) => void {
  return (next: boolean) => {
    props.onOpenChange?.(next);
  };
}
