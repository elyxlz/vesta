import { useEffect } from "react";

const SHOW_CLASS = "show-scrollbar";
const IDLE_MS = 1200;

function scrollableAncestor(node: EventTarget | null): HTMLElement | null {
  let el = node instanceof HTMLElement ? node : null;
  while (el) {
    const style = getComputedStyle(el);
    const overflowsY =
      (style.overflowY === "auto" || style.overflowY === "scroll") &&
      el.scrollHeight > el.clientHeight;
    const overflowsX =
      (style.overflowX === "auto" || style.overflowX === "scroll") &&
      el.scrollWidth > el.clientWidth;
    if (overflowsY || overflowsX) {
      return el;
    }
    el = el.parentElement;
  }
  return null;
}

// Native scrollbars stay hidden (a transparent thumb) until their container sees activity, then hide
// again after a short idle. Any pointer entering a scroll container, or any scroll, reveals it; a
// single idle timer takes it back down. A class is what works here: Blink honors scrollbar
// pseudo-elements gated by a class on the element, but not by the element's own `:hover`, so
// `:hover::-webkit-scrollbar-thumb` never repaints.
export function useAutoHideScrollbars(): void {
  useEffect(() => {
    let active: HTMLElement | null = null;
    let timer = 0;

    const hide = () => {
      if (active) {
        active.classList.remove(SHOW_CLASS);
        active = null;
      }
    };
    const show = (el: HTMLElement) => {
      if (active && active !== el) {
        active.classList.remove(SHOW_CLASS);
      }
      active = el;
      el.classList.add(SHOW_CLASS);
      window.clearTimeout(timer);
      timer = window.setTimeout(hide, IDLE_MS);
    };

    const onPointerOver = (event: PointerEvent) => {
      const el = scrollableAncestor(event.target);
      if (el) {
        show(el);
      }
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof HTMLElement) {
        show(event.target);
      }
    };
    // The pointer leaving the window (relatedTarget null) or the app losing focus fires no further
    // pointer events, so hide right away instead of waiting out the idle timer.
    const onMouseOut = (event: MouseEvent) => {
      if (!event.relatedTarget) {
        window.clearTimeout(timer);
        hide();
      }
    };
    const onBlur = () => {
      window.clearTimeout(timer);
      hide();
    };

    document.addEventListener("pointerover", onPointerOver, true);
    document.addEventListener("scroll", onScroll, true);
    document.addEventListener("mouseout", onMouseOut, true);
    window.addEventListener("blur", onBlur);
    return () => {
      document.removeEventListener("pointerover", onPointerOver, true);
      document.removeEventListener("scroll", onScroll, true);
      document.removeEventListener("mouseout", onMouseOut, true);
      window.removeEventListener("blur", onBlur);
      window.clearTimeout(timer);
    };
  }, []);
}
