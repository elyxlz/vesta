import { useMediaQuery } from "./use-media-query";

const MOBILE_BREAKPOINT = 768;

export function useIsMobile(): boolean {
  return useMediaQuery(`(max-width: ${String(MOBILE_BREAKPOINT - 1)}px)`);
}

// A narrow window driven by touch gets the thumb-reach controls (the bottom tab
// bar, drawers); a narrow window on a mouse keeps the top bar and dropdowns.
export function useIsTouchNarrow(): boolean {
  const finePointer = useMediaQuery("(hover: hover) and (pointer: fine)");
  return useIsMobile() && !finePointer;
}
