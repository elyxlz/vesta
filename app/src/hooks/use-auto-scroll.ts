import { useCallback, useRef } from "react";

export function useAutoScroll() {
  const wasNearBottomRef = useRef(true);

  const check = useCallback((el: HTMLElement | null) => {
    if (!el) return;
    wasNearBottomRef.current =
      el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
  }, []);

  const scroll = useCallback((el: HTMLElement | null) => {
    if (!wasNearBottomRef.current || !el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, []);

  return { check, scroll };
}
