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

      let focused = false;
      if (!isTextareaActive) {
        viewportHeightRef.current =
          baselineHeight === null
            ? viewportHeight
            : Math.max(baselineHeight, viewportHeight);
      } else if (baselineHeight === null || viewportHeight > baselineHeight) {
        viewportHeightRef.current = viewportHeight;
      } else {
        focused = baselineHeight - viewportHeight > 120;
      }

      writeFocused(focused);
      // Browsers that ignore interactive-widget=resizes-content (iOS Safari) keep the
      // layout viewport under the keyboard and pan it to reveal the caret, a pan that
      // any reflow while typing resets, hiding the composer. While the keyboard is up,
      // fit the app to the visual viewport instead so nothing ever needs panning.
      document.documentElement.style.height = focused
        ? `${viewportHeight}px`
        : "";
      if (focused) window.scrollTo(0, 0);
    };

    viewport.addEventListener("resize", syncKeyboardFocus);
    return () => {
      viewport.removeEventListener("resize", syncKeyboardFocus);
      document.documentElement.style.height = "";
    };
  }, [isMobile, setChatKeyboardFocused, textareaRef]);
}
