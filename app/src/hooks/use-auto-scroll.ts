import { useCallback, useRef } from "react";

const NEAR_BOTTOM_THRESHOLD = 80;

export function useAutoScroll() {
  const wasNearBottomRef = useRef(true);
  const userScrolledRef = useRef(false);
  const programmaticScrollRef = useRef(false);

  const check = useCallback((el: HTMLElement | null) => {
    if (!el) return;
    if (programmaticScrollRef.current) {
      programmaticScrollRef.current = false;
      wasNearBottomRef.current = true;
      return;
    }
    userScrolledRef.current = true;
    wasNearBottomRef.current =
      el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_BOTTOM_THRESHOLD;
  }, []);

  const scroll = useCallback((el: HTMLElement | null) => {
    if (!wasNearBottomRef.current || !el) return;
    programmaticScrollRef.current = true;
    el.scrollTop = el.scrollHeight;
  }, []);

  return { check, scroll };
}
