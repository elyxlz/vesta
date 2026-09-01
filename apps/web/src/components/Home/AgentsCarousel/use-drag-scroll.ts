import { useEffect, type RefObject } from "react";

// Past this much movement a press counts as a drag, so the trailing click is swallowed.
const DRAG_THRESHOLD_PX = 5;
// Fallback for restoring snap when `scrollend` never fires (unsupported, or the release already sat
// on a snap point so the smooth scroll is a no-op).
const SETTLE_FALLBACK_MS = 500;

export type DragPhase = "idle" | "dragging" | "settling";

// Mouse click-drag to scroll the carousel; touch already scrolls it natively, so this binds only for
// the mouse. During the drag it drives scrollLeft directly and reports "dragging" so the caller drops
// CSS scroll snapping (a free drag). On release it smooth-scrolls to the nearest card itself and only
// restores snapping once that settles, so the release glides instead of hard-snapping. It also
// swallows the click that ends a real drag so releasing never opens the card underneath.
export function useDragScroll(
  ref: RefObject<HTMLElement | null>,
  stride: number,
  onPhaseChange: (phase: DragPhase) => void,
): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let active = false;
    let moved = false;
    let startX = 0;
    let startScroll = 0;
    let settleCleanup: (() => void) | null = null;

    const clearSettle = () => {
      settleCleanup?.();
      settleCleanup = null;
    };

    const settle = () => {
      const target = Math.round(el.scrollLeft / stride) * stride;
      onPhaseChange("settling");
      el.scrollTo({ left: target, behavior: "smooth" });
      const finish = () => {
        clearSettle();
        onPhaseChange("idle");
      };
      el.addEventListener("scrollend", finish);
      const timer = window.setTimeout(finish, SETTLE_FALLBACK_MS);
      settleCleanup = () => {
        el.removeEventListener("scrollend", finish);
        clearTimeout(timer);
      };
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      clearSettle();
      active = true;
      moved = false;
      startX = event.clientX;
      startScroll = el.scrollLeft;
      el.setPointerCapture(event.pointerId);
      onPhaseChange("dragging");
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!active) return;
      const dx = event.clientX - startX;
      if (Math.abs(dx) > DRAG_THRESHOLD_PX) moved = true;
      el.scrollLeft = startScroll - dx;
    };
    const stop = (event: PointerEvent) => {
      if (!active) return;
      active = false;
      if (el.hasPointerCapture(event.pointerId))
        el.releasePointerCapture(event.pointerId);
      settle();
    };
    const onClickCapture = (event: MouseEvent) => {
      if (!moved) return;
      moved = false;
      event.preventDefault();
      event.stopPropagation();
    };
    // A drag over a card image/link would otherwise start a native drag-and-drop ghost.
    const onDragStart = (event: Event) => {
      if (active) event.preventDefault();
    };

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
    el.addEventListener("click", onClickCapture, { capture: true });
    el.addEventListener("dragstart", onDragStart);
    return () => {
      clearSettle();
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", stop);
      el.removeEventListener("pointercancel", stop);
      el.removeEventListener("click", onClickCapture, { capture: true });
      el.removeEventListener("dragstart", onDragStart);
    };
  }, [ref, stride, onPhaseChange]);
}
