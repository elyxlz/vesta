import { useCallback, useLayoutEffect, useState } from "react";

// The width twin of useMeasuredHeight: synchronous first measurement before
// paint, then ResizeObserver updates.
export function useMeasuredWidth(setWidth: (width: number) => void) {
  const [node, setNode] = useState<HTMLElement | null>(null);

  const ref = useCallback((element: HTMLElement | null) => {
    setNode(element);
  }, []);

  useLayoutEffect(() => {
    if (!node) return;
    setWidth(node.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const border = entry.borderBoxSize[0];
      setWidth(
        border ? border.inlineSize : entry.target.getBoundingClientRect().width,
      );
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      setWidth(0);
    };
  }, [node, setWidth]);

  return ref;
}
