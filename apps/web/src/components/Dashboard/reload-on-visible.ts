// The dashboard iframe is keyed on its service `rev`, so a bump remounts and reloads it. But while
// the desktop window is occluded (minimized or fully hidden), Chromium freezes the remounted frame
// and its reload never completes (`onLoad` never fires), leaving the dashboard stuck stale with no
// automatic recovery. When the window becomes visible again we reconcile: if the rev that actually
// finished loading is behind the current tree rev (or nothing ever loaded), a fresh mount is forced
// so the pending refresh runs the moment it can.
export function shouldReloadDashboard(args: {
  visible: boolean;
  hasDashboard: boolean;
  loadedRev: number | null;
  currentRev: number;
}): boolean {
  if (!args.visible || !args.hasDashboard) return false;
  return args.loadedRev !== args.currentRev;
}
