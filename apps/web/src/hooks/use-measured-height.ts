import { useCallback, useEffect, useState } from "react";

export function useMeasuredHeight(setHeight: (height: number) => void) {
  const [node, setNode] = useState<HTMLElement | null>(null);

  const ref = useCallback((element: HTMLElement | null) => {
    setNode(element);
  }, []);

  useEffect(() => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
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
