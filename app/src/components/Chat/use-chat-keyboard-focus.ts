import { useEffect, useRef, type RefObject } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { useLayout } from "@/stores/use-layout";

export function useChatKeyboardFocus(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
) {
  const isMobile = useIsMobile();
  const setChatKeyboardFocused = useLayout((s) => s.setChatKeyboardFocused);
  const viewportHeightRef = useRef<number | null>(null);
  const lastFocusedRef = useRef<boolean | null>(null);

  useEffect(() => {
    const writeFocused = (focused: boolean) => {
      if (lastFocusedRef.current === focused) return;
      lastFocusedRef.current = focused;
      setChatKeyboardFocused(focused);
    };

    return () => {
      writeFocused(false);
    };
  }, [setChatKeyboardFocused]);

  useEffect(() => {
    if (!isMobile) return;
    const viewport = window.visualViewport;
    if (!viewport) return;

    viewportHeightRef.current = viewport.height;

    const writeFocused = (focused: boolean) => {
      if (lastFocusedRef.current === focused) return;
      lastFocusedRef.current = focused;
      setChatKeyboardFocused(focused);
    };

    const syncKeyboardFocus = () => {
      const textarea = textareaRef.current;
      const isTextareaActive =
        !!textarea && document.activeElement === textarea;
      const viewportHeight = viewport.height;
      const baselineHeight = viewportHeightRef.current;

      if (!isTextareaActive) {
        viewportHeightRef.current =
          baselineHeight === null
            ? viewportHeight
            : Math.max(baselineHeight, viewportHeight);
        writeFocused(false);
        return;
      }

      if (baselineHeight === null || viewportHeight > baselineHeight) {
        viewportHeightRef.current = viewportHeight;
        writeFocused(false);
        return;
      }

      writeFocused(baselineHeight - viewportHeight > 120);
    };

    viewport.addEventListener("resize", syncKeyboardFocus);
    return () => {
      viewport.removeEventListener("resize", syncKeyboardFocus);
    };
  }, [isMobile, setChatKeyboardFocused, textareaRef]);
}
