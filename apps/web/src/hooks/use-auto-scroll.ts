import { useCallback, useRef, useState } from "react";

const NEAR_BOTTOM_THRESHOLD = 80;

export function useAutoScroll() {
  const wasNearBottomRef = useRef(true);
  const userScrolledRef = useRef(false);
  const programmaticScrollRef = useRef(false);
  const [isNearBottom, setIsNearBottom] = useState(true);

  const check = useCallback((el: HTMLElement | null) => {
    if (!el) return;
    if (programmaticScrollRef.current) {
      programmaticScrollRef.current = false;
      wasNearBottomRef.current = true;
      setIsNearBottom(true);
      return;
    }
    userScrolledRef.current = true;
    const near =
      el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_BOTTOM_THRESHOLD;
    wasNearBottomRef.current = near;
    setIsNearBottom(near);
  }, []);

  const scroll = useCallback((el: HTMLElement | null) => {
    if (!wasNearBottomRef.current || !el) return;
    programmaticScrollRef.current = true;
    el.scrollTop = el.scrollHeight;
  }, []);

  const scrollToBottom = useCallback((el: HTMLElement | null) => {
    if (!el) return;
    programmaticScrollRef.current = true;
    wasNearBottomRef.current = true;
    setIsNearBottom(true);
    el.scrollTop = el.scrollHeight;
  }, []);

  return { check, scroll, scrollToBottom, isNearBottom };
}
