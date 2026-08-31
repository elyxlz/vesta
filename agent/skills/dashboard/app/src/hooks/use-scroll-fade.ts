import { useCallback, useLayoutEffect, useRef, useState } from "react";

// A vertical fade that appears only on the edge a container can still scroll toward, so an
// overflowing list signals more content above or below and never fades at the very start or
// end. Pass per-edge fade sizes (CSS lengths, default 28px); pass `ref` to fade a scroll
// element owned elsewhere. Returns the ref, a mask style to spread, the live `edges` (for a
// caller building a bespoke mask), and an `update` for content changes it cannot observe.
const DEFAULT_FADE = "28px";

// The fade grows in over the first FADE_GROW_PX of scroll away from an edge (and shrinks back over
// the last FADE_GROW_PX approaching one), so it eases on with the scroll instead of snapping.
const FADE_GROW_PX = 33;

// The bottom fade shared by every scroll surface (the page, the console, the gateway log
// viewer): the tail softens by this many px so the last line never cuts hard against the edge.
export const BOTTOM_FADE_PX = 15;

// Under-chrome curve: content holds near-invisible through the first two-thirds, then ramps to
// solid, so it dissolves cleanly as it slides beneath a floating header or footer. This wants a
// tall region (chrome height) and would just eat content on a small bare edge.
function fadeInStopsChrome(fade: string): string {
  return `transparent, rgba(0,0,0,0.05) calc(${fade} * 0.31), rgba(0,0,0,0.16) calc(${fade} * 0.65), black ${fade}`;
}

function fadeOutStopsChrome(fade: string): string {
  return `black calc(100% - ${fade}), rgba(0,0,0,0.16) calc(100% - ${fade} * 0.65), rgba(0,0,0,0.05) calc(100% - ${fade} * 0.31), transparent`;
}

// Bare-edge curve: a gentle near-linear dissolve that still reads as a fade on a small region, for
// an edge with nothing floating over it.
function fadeInStopsBare(fade: string): string {
  return `transparent, rgba(0,0,0,0.4) calc(${fade} * 0.5), black ${fade}`;
}

function fadeOutStopsBare(fade: string): string {
  return `black calc(100% - ${fade}), rgba(0,0,0,0.4) calc(100% - ${fade} * 0.5), transparent`;
}

function fadeInStops(fade: string, chrome: boolean): string {
  return chrome ? fadeInStopsChrome(fade) : fadeInStopsBare(fade);
}

function fadeOutStops(fade: string, chrome: boolean): string {
  return chrome ? fadeOutStopsChrome(fade) : fadeOutStopsBare(fade);
}

// The mask fades only the edges that can currently scroll, so an edge at the very start/end stays
// crisp. `topLen`/`bottomLen` already carry the grown region size.
function buildMask(
  top: { on: boolean; len: string; chrome: boolean },
  bottom: { on: boolean; len: string; chrome: boolean },
): string | undefined {
  const start = top.on ? fadeInStops(top.len, top.chrome) : null;
  const end = bottom.on ? fadeOutStops(bottom.len, bottom.chrome) : null;
  const stops = [start, end].filter((part) => part !== null);
  return stops.length > 0
    ? `linear-gradient(to bottom, ${stops.join(", ")})`
    : undefined;
}

export interface ScrollEdges {
  top: boolean;
  bottom: boolean;
}

interface ScrollFadeOptions<T extends HTMLElement> {
  top?: string;
  bottom?: string;
  // An edge backed by floating chrome (a header/footer) uses the under-chrome curve; a bare edge
  // (default) uses the gentle curve that still reads as a fade on a small region.
  topChrome?: boolean;
  bottomChrome?: boolean;
  ref?: React.RefObject<T | null>;
}

export function useScrollFade<T extends HTMLElement>(
  options?: ScrollFadeOptions<T>,
) {
  const topFade = options?.top ?? DEFAULT_FADE;
  const bottomFade = options?.bottom ?? DEFAULT_FADE;
  const topChrome = options?.topChrome ?? false;
  const bottomChrome = options?.bottomChrome ?? false;
  const internalRef = useRef<T>(null);
  const ref = options?.ref ?? internalRef;
  // Per-edge fade strength in [0, 1], grown from the distance scrolled past the edge. Quantized so
  // a slow scroll does not re-render every pixel; 0 on an edge means no fade there.
  const [factors, setFactors] = useState({ top: 0, bottom: 0 });
  const updateRef = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const grown = (distance: number) =>
      Math.round(Math.min(Math.max(distance / FADE_GROW_PX, 0), 1) * 20) / 20;
    const update = () => {
      const maxScroll = el.scrollHeight - el.clientHeight;
      const top = grown(el.scrollTop);
      const bottom = grown(maxScroll - el.scrollTop);
      setFactors((prev) =>
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

  // The grown factor scales the fade region, so the mask thickens with the scroll rather than
  // appearing at full size the instant an edge can scroll.
  const maskImage = buildMask(
    {
      on: factors.top > 0,
      len: `calc(${topFade} * ${String(factors.top)})`,
      chrome: topChrome,
    },
    {
      on: factors.bottom > 0,
      len: `calc(${bottomFade} * ${String(factors.bottom)})`,
      chrome: bottomChrome,
    },
  );

  const style: React.CSSProperties | undefined = maskImage
    ? { maskImage, WebkitMaskImage: maskImage }
    : undefined;

  const edges: ScrollEdges = {
    top: factors.top > 0,
    bottom: factors.bottom > 0,
  };
  return { ref, style, edges, update };
}
