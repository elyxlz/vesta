import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useLayout } from "@/stores/use-layout";

// Floor so a stacked/low element (e.g. on a single-column mobile layout, where
// it sits below other cards) never collapses — it falls back to a usable height
// and the page scrolls normally instead.
const MIN_HEIGHT = 240;

// Closest scrollable ancestor — its visible area, not the raw viewport, is the
// space the element must fit inside (the settings page scroll container sits
// below the navbar, so window.innerHeight overshoots its real bottom).
function findScrollParent(node: HTMLElement | null): HTMLElement | null {
  let el = node?.parentElement ?? null;
  while (el) {
    const overflowY = getComputedStyle(el).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") return el;
    el = el.parentElement;
  }
  return null;
}

// Height that makes the ref'd element fill from its top down to the scroll
// container's visible bottom (minus a gap), so the surrounding page never
// scrolls. The returned `ref` is a callback ref so it measures the moment the
// element attaches — the element can mount late (e.g. after a fetch) or only on
// some breakpoints. It also re-measures on window resize and once the navbar
// settles its height.
export function useFillHeight(bottomGap: number) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const elRef = useRef<HTMLDivElement | null>(null);
  const [height, setHeight] = useState(0);

  const measure = useCallback(() => {
    const el = elRef.current;
    if (!el) return;
    const top = el.getBoundingClientRect().top;
    const scroller = findScrollParent(el);
    const visibleBottom = scroller
      ? scroller.getBoundingClientRect().top + scroller.clientHeight
      : window.innerHeight;
    setHeight(
      Math.max(MIN_HEIGHT, Math.floor(visibleBottom - top - bottomGap)),
    );
  }, [bottomGap]);

  const ref = useCallback(
    (node: HTMLDivElement | null) => {
      elRef.current = node;
      if (node) measure();
    },
    [measure],
  );

  useLayoutEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure, navbarHeight]);

  return { ref, height };
}
