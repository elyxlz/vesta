import { useCallback, useLayoutEffect, useState } from "react";

// useLayoutEffect + an immediate synchronous measurement commits the real
// size before the browser paints. Without it the consumer (navbar-height page
// padding) paints one frame at the stale default and the content visibly jumps
// when the async ResizeObserver callback finally lands.
export function useMeasuredSize(
  axis: "width" | "height",
  setSize: (size: number) => void,
) {
  const [node, setNode] = useState<HTMLElement | null>(null);

  const ref = useCallback((element: HTMLElement | null) => {
    setNode(element);
  }, []);

  useLayoutEffect(() => {
    if (!node) return;
    setSize(node.getBoundingClientRect()[axis]);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const border = entry.borderBoxSize[0];
      setSize(
        border
          ? axis === "width"
            ? border.inlineSize
            : border.blockSize
          : entry.target.getBoundingClientRect()[axis],
      );
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      setSize(0);
    };
  }, [node, setSize, axis]);

  return ref;
}
