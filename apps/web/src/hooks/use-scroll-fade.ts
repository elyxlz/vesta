import { useCallback, useLayoutEffect, useRef, useState } from "react";

// A vertical fade that appears only on the edge a container can still scroll toward, so an
// overflowing list signals more content above or below and never fades at the very start or
// end. Pass per-edge fade sizes (CSS lengths, default 28px); pass `ref` to fade a scroll
// element owned elsewhere. Returns the ref, a mask style to spread, the live `edges` (for a
// caller building a bespoke mask), and an `update` for content changes it cannot observe.
const DEFAULT_FADE = "28px";

export interface ScrollEdges {
  top: boolean;
  bottom: boolean;
}

interface ScrollFadeOptions<T extends HTMLElement> {
  top?: string;
  bottom?: string;
  ref?: React.RefObject<T | null>;
}

export function useScrollFade<T extends HTMLElement>(
  options?: ScrollFadeOptions<T>,
) {
  const topFade = options?.top ?? DEFAULT_FADE;
  const bottomFade = options?.bottom ?? DEFAULT_FADE;
  const internalRef = useRef<T>(null);
  const ref = options?.ref ?? internalRef;
  const [edges, setEdges] = useState<ScrollEdges>({
    top: false,
    bottom: false,
  });
  const updateRef = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const top = el.scrollTop > 1;
      const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
      setEdges((prev) =>
        prev.top === top && prev.bottom === bottom ? prev : { top, bottom },
      );
    };
    updateRef.current = update;
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    // The scroll element's own size rarely changes; its content growing is what flips an
    // edge, so observe the content wrapper too.
    const content = el.firstElementChild;
    if (content) observer.observe(content);
    return () => {
      el.removeEventListener("scroll", update);
      observer.disconnect();
      updateRef.current = null;
    };
  }, [ref]);

  // Stable: a caller (a fixed-height box a ResizeObserver never fires for) recomputes edges
  // when its content changes.
  const update = useCallback(() => updateRef.current?.(), []);

  const maskImage =
    edges.top && edges.bottom
      ? `linear-gradient(to bottom, transparent, black ${topFade}, black calc(100% - ${bottomFade}), transparent)`
      : edges.top
        ? `linear-gradient(to bottom, transparent, black ${topFade})`
        : edges.bottom
          ? `linear-gradient(to bottom, black calc(100% - ${bottomFade}), transparent)`
          : undefined;

  const style: React.CSSProperties | undefined = maskImage
    ? { maskImage, WebkitMaskImage: maskImage }
    : undefined;

  return { ref, style, edges, update };
}
