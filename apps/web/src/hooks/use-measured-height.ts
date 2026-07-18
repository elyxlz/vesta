import { useCallback, useLayoutEffect, useState } from "react";

export function useMeasuredHeight(setHeight: (height: number) => void) {
  const [node, setNode] = useState<HTMLElement | null>(null);

  const ref = useCallback((element: HTMLElement | null) => {
    setNode(element);
  }, []);

  // useLayoutEffect + an immediate synchronous measurement commits the real
  // height before the browser paints. Without it the consumer (navbar-height page
  // padding) paints one frame at the stale default and the content visibly jumps
  // when the async ResizeObserver callback finally lands.
  useLayoutEffect(() => {
    if (!node) return;
    setHeight(node.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const border = entry.borderBoxSize[0];
      setHeight(
        border ? border.blockSize : entry.target.getBoundingClientRect().height,
      );
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      setHeight(0);
    };
  }, [node, setHeight]);

  return ref;
}
