import { useCallback, useLayoutEffect, useRef, useState } from "react";

// A vertical fade that appears only on the edge a container can still scroll
// toward, so an overflowing list signals more content above or below. Returns a
// ref for the scroll element, a mask style to spread on it, and an `update` to
// call when the content (not the box) changes size.
const FADE = "28px";

export function useScrollFade<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });

  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const top = el.scrollTop > 1;
    const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setEdges((prev) =>
      prev.top === top && prev.bottom === bottom ? prev : { top, bottom },
    );
  }, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, [update]);

  const maskImage =
    edges.top && edges.bottom
      ? `linear-gradient(to bottom, transparent, black ${FADE}, black calc(100% - ${FADE}), transparent)`
      : edges.top
        ? `linear-gradient(to bottom, transparent, black ${FADE})`
        : edges.bottom
          ? `linear-gradient(to bottom, black calc(100% - ${FADE}), transparent)`
          : undefined;

  const style: React.CSSProperties | undefined = maskImage
    ? { maskImage, WebkitMaskImage: maskImage }
    : undefined;

  return { ref, style, update };
}
