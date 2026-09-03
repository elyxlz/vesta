import { useEffect, type RefObject } from "react";

// Past this much movement a press becomes a drag; only then does it capture the pointer and take
// over scrolling, so a plain click (which never moves this far) passes straight through to the card.
const DRAG_THRESHOLD_PX = 5;
// Fallback for restoring snap when `scrollend` never fires (unsupported, or the release already sat
// on a snap point so the smooth scroll is a no-op).
const SETTLE_FALLBACK_MS = 500;

export type DragPhase = "idle" | "dragging" | "settling";

// Mouse click-drag to scroll the carousel; touch already scrolls it natively, so this binds only for
// the mouse. It captures the pointer and reports "dragging" only once the press has moved past the
// threshold, so a click reaches the card underneath, then drives scrollLeft directly (snapping off).
// On release it smooth-scrolls to the nearest card and restores snapping once that settles, and it
// swallows the click that ends a real drag so releasing never opens the card.
export function useDragScroll(
  ref: RefObject<HTMLElement | null>,
  stride: number,
  onPhaseChange: (phase: DragPhase) => void,
): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let pressed = false;
    let dragging = false;
    let suppressNextClick = false;
    let startX = 0;
    let startScroll = 0;
    let pointerId = -1;
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
      pressed = true;
      dragging = false;
      suppressNextClick = false;
      startX = event.clientX;
      startScroll = el.scrollLeft;
      pointerId = event.pointerId;
      // No capture and no drag state yet: a press that never moves must click through to the card.
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!pressed) return;
      const dx = event.clientX - startX;
      if (!dragging) {
        if (Math.abs(dx) <= DRAG_THRESHOLD_PX) return;
        dragging = true;
        el.setPointerCapture(pointerId);
        onPhaseChange("dragging");
      }
      el.scrollLeft = startScroll - dx;
    };
    const stop = () => {
      if (!pressed) return;
      pressed = false;
      if (!dragging) return;
      dragging = false;
      suppressNextClick = true;
      if (el.hasPointerCapture(pointerId)) el.releasePointerCapture(pointerId);
      settle();
    };
    const onClickCapture = (event: MouseEvent) => {
      if (!suppressNextClick) return;
      suppressNextClick = false;
      event.preventDefault();
      event.stopPropagation();
    };
    // A drag over a card image/link would otherwise start a native drag-and-drop ghost.
    const onDragStart = (event: Event) => {
      if (pressed) event.preventDefault();
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
