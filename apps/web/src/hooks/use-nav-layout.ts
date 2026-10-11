import { useIsMobile } from "./use-mobile";
import { useMediaQuery } from "./use-media-query";

// How a window moves between pages. A narrow touch window gets the thumb-reach
// controls (the bottom tab bar, the drawer menu); a narrow mouse window keeps
// them in the top bar, where the page switch takes the bell's room.
export type NavLayout = "wide" | "mouse-narrow" | "touch-narrow";

export function useNavLayout(): NavLayout {
  const narrow = useIsMobile();
  const finePointer = useMediaQuery("(hover: hover) and (pointer: fine)");
  if (!narrow) return "wide";
  return finePointer ? "mouse-narrow" : "touch-narrow";
}
